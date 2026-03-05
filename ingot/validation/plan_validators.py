"""Concrete plan validators for the INGOT workflow.

Each validator is a small, focused class that checks one aspect of
a generated plan. The factory function at the bottom creates the
default registry with all standard validators.
"""

import bisect
import re

from ingot.discovery.citation_utils import (
    IDENTIFIER_RE,
    MAX_CITATION_FILE_SIZE,
    find_nearest_code_block,
    safe_resolve_path,
)
from ingot.utils.logging import log_message
from ingot.validation.base import (
    ValidationContext,
    ValidationFinding,
    ValidationSeverity,
    Validator,
    ValidatorRegistry,
)

# =============================================================================
# Shared Utility Functions
# =============================================================================

# Common patterns for paths to skip (not real file references).
# Used by FileExistsValidator and TestCoverageValidator.
_COMMON_SKIP_PATTERNS = [
    re.compile(r"[{}<>*]"),  # Templated or glob
    re.compile(r"^path/to/"),  # Placeholder
    re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://"),  # URLs (http, s3, ssh, file, git, gs, etc.)
    re.compile(r"^(?:data|mailto):"),  # Schemes without //
]

# Matches a valid line-number suffix: "42" or "42-58".
# Used to strip `:line` or `:line-line` from file path references.
_LINE_SUFFIX_RE = re.compile(r"^\d+(-\d+)?$")

# Two complementary code-block parsers coexist in this module:
#
# 1. Line-based parser (_extract_code_blocks): returns (open_line, close_line)
#    index pairs. Used when validators need exact line numbers (e.g.,
#    SnippetCompletenessValidator, CitationContentValidator).
#
# 2. Regex parser (_FENCED_CODE_BLOCK_RE): operates on full strings. Used for
#    stripping blocks (RequiredSectionsValidator) or getting byte offsets.
#
# Both use the same ``` fence detection and should be kept in sync.
_FENCED_CODE_BLOCK_RE = re.compile(
    r"^```[^\n]*\n.*?^```\s*$",
    re.MULTILINE | re.DOTALL,
)

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# Module-level marker patterns shared between validators and PlanFixer.
UNVERIFIED_RE = re.compile(r"<!--\s*UNVERIFIED:.*?-->", re.DOTALL)
NEW_FILE_MARKER_RE = re.compile(r"<!--\s*NEW_FILE(?::.*?)?\s*-->", re.IGNORECASE)


def _extract_code_blocks(lines: list[str]) -> tuple[list[tuple[int, int]], bool]:
    """Parse fenced code blocks from markdown lines.

    Returns:
        Tuple of (blocks, unbalanced) where blocks is a list of
        (open_line, close_line) pairs and unbalanced is True if there
        is an unclosed code fence.
    """
    blocks: list[tuple[int, int]] = []
    in_code_block = False
    open_line = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                open_line = i
            else:
                in_code_block = False
                blocks.append((open_line, i))
    return blocks, in_code_block


def _strip_fenced_code_blocks(content: str) -> str:
    """Remove fenced code blocks from content.

    Used to prevent headings or names inside ``` blocks from matching
    as real sections or coverage references.
    """
    return _FENCED_CODE_BLOCK_RE.sub("", content)


def _build_code_block_ranges(content: str) -> tuple[list[int], list[int]]:
    """Return sorted (starts, ends) offset lists for fenced code blocks.

    Each pair ``(starts[i], ends[i])`` delimits one fenced code block.
    """
    starts: list[int] = []
    ends: list[int] = []
    for m in _FENCED_CODE_BLOCK_RE.finditer(content):
        starts.append(m.start())
        ends.append(m.end())
    return starts, ends


def _is_inside_code_block(starts: list[int], ends: list[int], offset: int) -> bool:
    """Check whether *offset* falls inside any fenced code block range.

    Uses ``bisect.bisect_right`` for O(log N) lookup.
    """
    idx = bisect.bisect_right(starts, offset) - 1
    if idx < 0:
        return False
    return offset < ends[idx]


def _build_line_index(content: str) -> list[int]:
    """Build a sorted list of newline character offsets for O(log N) lookups.

    Returns a list of positions where '\\n' occurs in *content*.
    Uses ``re.finditer`` for better performance on large inputs compared
    to character-by-character enumeration.
    """
    return [m.start() for m in re.finditer(r"\n", content)]


def _line_number_at(line_index: list[int], offset: int) -> int:
    """Return the 1-based line number for a character *offset*.

    Uses ``bisect.bisect_right`` for O(log N) lookup against the
    pre-built *line_index*.
    """
    return bisect.bisect_right(line_index, offset) + 1


def _extract_plan_sections(content: str, section_names: list[str]) -> str:
    """Extract text from specific plan sections.

    Scans for ``#{1,3}`` headings (not ``####``+) and checks whether the
    heading text matches any target *section_names* (case-insensitive
    partial match).  Returns the concatenated text from matched sections.
    """
    matches = list(_HEADING_RE.finditer(content))

    if not matches:
        return ""

    parts: list[str] = []
    for idx, m in enumerate(matches):
        heading_text = m.group(2).strip()
        # Check case-insensitive partial match against any target section
        if not any(name.lower() in heading_text.lower() for name in section_names):
            continue
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        parts.append(content[start:end])

    return "\n".join(parts)


class RequiredSectionsValidator(Validator):
    """Check that all required plan sections are present."""

    REQUIRED = [
        "Summary",
        "Technical Approach",
        "Implementation Steps",
        "Testing Strategy",
        "Potential Risks",
        "Out of Scope",
    ]

    @property
    def name(self) -> str:
        return "Required Sections"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        # Strip fenced code blocks so headings inside ``` don't count
        stripped = _strip_fenced_code_blocks(content)
        for section in self.REQUIRED:
            # Case-insensitive, allows partial match
            # e.g. "Potential Risks or Considerations" matches "Potential Risks"
            pattern = re.compile(
                r"^#{1,3}\s+.*" + re.escape(section),
                re.IGNORECASE | re.MULTILINE,
            )
            if not pattern.search(stripped):
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.ERROR,
                        message=f"Missing required section: '{section}'",
                        suggestion=f"Add a '## {section}' section to the plan.",
                    )
                )
        return findings


class FileExistsValidator(Validator):
    """Check that file paths referenced in the plan exist on the filesystem."""

    # Match backtick-quoted strings containing at least one / and a file extension
    _PATH_RE = re.compile(r"`([^`\n]*?(?:/[^`\n]*?\.\w{1,8})[^`\n]*?)`")

    # Match backtick-quoted root files (no slash) with common extensions
    _ROOT_FILE_RE = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_.-]*\.\w{1,8})`")

    # Maximum length for extracted paths (reject absurdly long false positives)
    _MAX_PATH_LENGTH = 300

    # Common file extensions to filter root-file matches (avoid false positives)
    _COMMON_FILE_EXTENSIONS: frozenset[str] = frozenset(
        {
            "py",
            "js",
            "ts",
            "tsx",
            "jsx",
            "md",
            "json",
            "toml",
            "yaml",
            "yml",
            "cfg",
            "ini",
            "txt",
            "rst",
            "html",
            "css",
            "scss",
            "less",
            "xml",
            "sh",
            "bash",
            "zsh",
            "fish",
            "bat",
            "ps1",
            "rb",
            "go",
            "rs",
            "java",
            "kt",
            "c",
            "cpp",
            "h",
            "hpp",
            "cs",
            "swift",
            "m",
            "lock",
            "sql",
            "graphql",
            "proto",
            "tf",
            "hcl",
        }
    )

    # Known extensionless filenames that should be treated as files
    # Sorted tuple for deterministic regex construction.
    _KNOWN_EXTENSIONLESS: tuple[str, ...] = (
        "Brewfile",
        "Containerfile",
        "Dockerfile",
        "Gemfile",
        "Justfile",
        "Makefile",
        "Procfile",
        "Rakefile",
        "Taskfile",
        "Vagrantfile",
    )
    _EXTENSIONLESS_RE = re.compile(
        r"`(" + "|".join(re.escape(f) for f in _KNOWN_EXTENSIONLESS) + r")`"
    )

    # Characters to strip from extracted paths
    _STRIP_CHARS = ".,;:()\"' "

    # Paths to skip (not real file references)
    _SKIP_PATTERNS = _COMMON_SKIP_PATTERNS

    # Detect UNVERIFIED markers (references module-level pattern)
    _UNVERIFIED_RE = UNVERIFIED_RE

    # Detect backtick-quoted paths that are preceded by creation keywords.
    # Requires the keyword to be directly before the backtick path (with only
    # optional markdown formatting between) to avoid false positives from
    # incidental usage of "Create" in prose on lines referencing existing files.
    # e.g. "Create `src/new.py`" matches, but "Create a new endpoint in `src/existing.py`" does not.
    _NEW_FILE_PRE_PATH_RE = re.compile(
        r"(?:^|\b)(?:Create|Creating|New\s+file)\b\s*[:*]*\s*(`[^`\n]+`)",
        re.IGNORECASE | re.MULTILINE,
    )
    # Detect backtick-quoted paths followed by "(NEW FILE)" marker.
    _NEW_FILE_POST_PATH_RE = re.compile(
        r"(`[^`\n]+`)\s*\(NEW\s+FILE\)",
        re.IGNORECASE,
    )
    # Explicit marker for new files (references module-level pattern).
    # Applied line-wide since these markers are explicit and unambiguous.
    _NEW_FILE_MARKER_RE = NEW_FILE_MARKER_RE

    @property
    def name(self) -> str:
        return "File Exists"

    def _extract_paths(self, content: str) -> list[tuple[str, int]]:
        """Extract (normalized_path, line_number) pairs from plan content."""
        line_index = _build_line_index(content)
        cb_starts, cb_ends = _build_code_block_ranges(content)

        # Find line numbers that contain UNVERIFIED markers
        unverified_lines: set[int] = set()
        for m in self._UNVERIFIED_RE.finditer(content):
            unverified_lines.add(_line_number_at(line_index, m.start()))

        # Find character offsets of backtick-quoted paths adjacent to creation
        # keywords.  Only the specific path next to the keyword is skipped,
        # not every path on the same line.
        new_file_offsets: set[int] = set()
        for m in self._NEW_FILE_PRE_PATH_RE.finditer(content):
            new_file_offsets.add(m.start(1))
        for m in self._NEW_FILE_POST_PATH_RE.finditer(content):
            new_file_offsets.add(m.start(1))

        # <!-- NEW_FILE --> markers are explicit enough to apply line-wide.
        new_file_lines: set[int] = set()
        for i, line in enumerate(content.splitlines(), 1):
            if self._NEW_FILE_MARKER_RE.search(line):
                new_file_lines.add(i)

        # Collect matches from all three regexes (_PATH_RE, _ROOT_FILE_RE,
        # _EXTENSIONLESS_RE).  Because the regexes can match overlapping text
        # (e.g., `setup.py` matches both _PATH_RE and _ROOT_FILE_RE), we
        # deduplicate by character offset so each backtick-quoted span is
        # only processed once.
        seen_offsets: set[int] = set()
        raw_matches: list[tuple[str, int, int]] = []  # (raw_text, offset, line_num)

        for match in self._PATH_RE.finditer(content):
            if match.start() not in seen_offsets:
                if _is_inside_code_block(cb_starts, cb_ends, match.start()):
                    continue
                seen_offsets.add(match.start())
                line_num = _line_number_at(line_index, match.start())
                raw_matches.append((match.group(1), match.start(), line_num))

        for match in self._ROOT_FILE_RE.finditer(content):
            if match.start() not in seen_offsets:
                if _is_inside_code_block(cb_starts, cb_ends, match.start()):
                    continue
                raw = match.group(1)
                # Only accept if extension is common
                ext = raw.rsplit(".", 1)[-1].lower() if "." in raw else ""
                if ext in self._COMMON_FILE_EXTENSIONS:
                    seen_offsets.add(match.start())
                    line_num = _line_number_at(line_index, match.start())
                    raw_matches.append((raw, match.start(), line_num))

        for match in self._EXTENSIONLESS_RE.finditer(content):
            if match.start() not in seen_offsets:
                if _is_inside_code_block(cb_starts, cb_ends, match.start()):
                    continue
                seen_offsets.add(match.start())
                line_num = _line_number_at(line_index, match.start())
                raw_matches.append((match.group(1), match.start(), line_num))

        results: list[tuple[str, int]] = []
        for raw_text, offset, line_num in raw_matches:
            if line_num in unverified_lines or line_num in new_file_lines:
                continue
            if offset in new_file_offsets:
                continue

            raw_path = raw_text.strip(self._STRIP_CHARS)

            # Skip absurdly long paths (false positives from multi-line spans)
            if len(raw_path) > self._MAX_PATH_LENGTH:
                continue

            # Split off :line_number suffix
            if ":" in raw_path:
                parts = raw_path.rsplit(":", 1)
                # Only split if the part after : looks like a line number
                if _LINE_SUFFIX_RE.match(parts[1]):
                    raw_path = parts[0]

            # Skip templated/glob/placeholder paths
            skip = False
            for skip_pattern in self._SKIP_PATTERNS:
                if skip_pattern.search(raw_path):
                    skip = True
                    break
            if skip:
                continue

            results.append((raw_path, line_num))

        return results

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        if context.repo_root is None:
            return []

        findings: list[ValidationFinding] = []
        paths = self._extract_paths(content)
        seen: set[str] = set()

        for path_str, line_number in paths:
            if path_str in seen:
                continue
            seen.add(path_str)

            full_path = context.repo_root / path_str
            try:
                resolved = full_path.resolve()
                if not resolved.is_relative_to(context.repo_root.resolve()):
                    continue
            except (ValueError, OSError):
                continue
            if not resolved.exists():
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.ERROR,
                        message=f"File not found: `{path_str}`",
                        line_number=line_number,
                        suggestion=(
                            "Verify the file path exists in the repository. "
                            "For new files to create, use 'Create `path`' or "
                            "<!-- NEW_FILE --> on the same line. "
                            "For unverified paths, use <!-- UNVERIFIED: reason -->."
                        ),
                        metadata={"path": path_str},
                    )
                )

        return findings


class PatternSourceValidator(Validator):
    """Check that code snippets cite a Pattern source reference."""

    _PATTERN_SOURCE_RE = re.compile(
        r"Pattern\s+source:\s*`?([^`\n]+\.\w{1,8}:\d+(?:-\d+)?)`?",
        re.IGNORECASE,
    )
    _NO_PATTERN_MARKER_RE = re.compile(r"<!--\s*NO_EXISTING_PATTERN:", re.IGNORECASE)

    _WINDOW_LINES = 5  # Lines before/after code block to search for citation

    @property
    def name(self) -> str:
        return "Pattern Source"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        lines = content.splitlines()

        code_blocks, unbalanced = _extract_code_blocks(lines)

        # Warn about unbalanced fence
        if unbalanced:
            # Find the last opening fence line
            fence_lines = [i for i, ln in enumerate(lines) if ln.strip().startswith("```")]
            last_fence = fence_lines[-1] if fence_lines else 0
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Unbalanced code fence at line {last_fence + 1}: "
                        f"opening ``` without matching close."
                    ),
                    line_number=last_fence + 1,
                    suggestion="Add a closing ``` to balance the code block.",
                )
            )

        # Check each code block for pattern source citation
        for block_open, block_close in code_blocks:
            # Skip trivially short blocks (< 3 lines of content)
            content_lines = block_close - block_open - 1
            if content_lines < 3:
                continue

            # Extract window before and after the code block
            window_start = max(0, block_open - self._WINDOW_LINES)
            window_end = min(len(lines), block_close + self._WINDOW_LINES + 1)
            window_text = "\n".join(lines[window_start:window_end])

            has_source = self._PATTERN_SOURCE_RE.search(window_text)
            has_no_pattern = self._NO_PATTERN_MARKER_RE.search(window_text)

            if not has_source and not has_no_pattern:
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Code block at line {block_open + 1} has no "
                            f"'Pattern source:' citation or NO_EXISTING_PATTERN marker."
                        ),
                        line_number=block_open + 1,
                        suggestion=(
                            "Add 'Pattern source: path/to/file:line-line' before the "
                            "code block, or '<!-- NO_EXISTING_PATTERN: description -->'."
                        ),
                    )
                )

        return findings


class UnresolvedMarkersValidator(Validator):
    """Detect and report UNVERIFIED, NO_EXISTING_PATTERN, NEW_FILE, NO_TEST_NEEDED, or TRIVIAL_STEP markers."""

    _UNVERIFIED_RE = re.compile(
        r"<!--\s*UNVERIFIED:\s*(.*?)\s*-->",
        re.IGNORECASE,
    )
    _NO_PATTERN_RE = re.compile(
        r"<!--\s*NO_EXISTING_PATTERN:\s*(.*?)\s*-->",
        re.IGNORECASE,
    )
    _NEW_FILE_RE = re.compile(
        r"<!--\s*NEW_FILE(?::\s*(.*?))?\s*-->",
        re.IGNORECASE,
    )
    _NO_TEST_NEEDED_RE = re.compile(
        r"<!--\s*NO_TEST_NEEDED:\s*(.*?)\s*-->",
        re.IGNORECASE,
    )
    _TRIVIAL_STEP_RE = re.compile(
        r"<!--\s*TRIVIAL_STEP:\s*(.*?)\s*-->",
        re.IGNORECASE,
    )

    @property
    def name(self) -> str:
        return "Unresolved Markers"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        line_index = _build_line_index(content)

        for match in self._UNVERIFIED_RE.finditer(content):
            line_number = _line_number_at(line_index, match.start())
            reason = match.group(1).strip()
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=f"UNVERIFIED marker: {reason}",
                    line_number=line_number,
                )
            )

        for match in self._NO_PATTERN_RE.finditer(content):
            line_number = _line_number_at(line_index, match.start())
            desc = match.group(1).strip()
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=f"NO_EXISTING_PATTERN marker: {desc}",
                    line_number=line_number,
                )
            )

        for match in self._NEW_FILE_RE.finditer(content):
            line_number = _line_number_at(line_index, match.start())
            desc = (match.group(1) or "").strip()
            msg = f"NEW_FILE marker: {desc}" if desc else "NEW_FILE marker"
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=msg,
                    line_number=line_number,
                )
            )

        for match in self._NO_TEST_NEEDED_RE.finditer(content):
            line_number = _line_number_at(line_index, match.start())
            desc = match.group(1).strip()
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=f"NO_TEST_NEEDED marker: {desc}",
                    line_number=line_number,
                )
            )

        for match in self._TRIVIAL_STEP_RE.finditer(content):
            line_number = _line_number_at(line_index, match.start())
            desc = match.group(1).strip()
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=f"TRIVIAL_STEP marker: {desc}",
                    line_number=line_number,
                )
            )

        return findings


class DiscoveryCoverageValidator(Validator):
    """Check that items from researcher discovery are referenced in the plan.

    Ensures entries from Interface & Class Hierarchy and Call Sites sections
    of the researcher output are either mentioned in Implementation Steps
    or explicitly listed in Out of Scope.

    Lightweight: uses string/path matching (not semantic analysis).
    """

    # Names shorter than this are skipped to avoid noisy false positives
    # (e.g., "get", "set", "run" match too broadly in plan text).
    _MIN_NAME_LENGTH = 3

    def __init__(self, researcher_output: str = "") -> None:
        self._researcher_output = researcher_output

    @property
    def name(self) -> str:
        return "Discovery Coverage"

    def _extract_names_from_section(self, section_header: str) -> list[str]:
        """Extract interface/class/method names from a researcher output section.

        Reuses :func:`_extract_plan_sections` to locate the target ``###``
        section, then scans for ``####`` sub-headings within it.
        """
        if not self._researcher_output:
            return []

        # Delegate section extraction to the shared utility.
        section_text = _extract_plan_sections(self._researcher_output, [section_header])
        if not section_text:
            return []

        names: list[str] = []
        for line in section_text.splitlines():
            stripped = line.strip()
            # Extract names from #### headers (e.g., "#### `InterfaceName`")
            if stripped.startswith("#### "):
                name_match = re.search(r"`([^`]+)`", stripped)
                if name_match:
                    name = name_match.group(1).removesuffix("()")
                    names.append(name)
                else:
                    name = stripped.lstrip("#").strip()
                    if name:
                        names.append(name)

        return names

    # Target sections for coverage checking
    _TARGET_SECTIONS = ["Implementation Steps", "Testing Strategy", "Out of Scope"]

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        if not self._researcher_output:
            return []

        findings: list[ValidationFinding] = []

        # Extract text from target sections only
        restricted_text = _extract_plan_sections(content, self._TARGET_SECTIONS)
        if restricted_text:
            # Strip code blocks from restricted text
            search_text = _strip_fenced_code_blocks(restricted_text)
        else:
            # Fallback: if no target sections found (malformed plan), search full content
            log_message(
                "DiscoveryCoverageValidator: no target sections found in plan, "
                "falling back to full-content search (may be more lenient)"
            )
            search_text = _strip_fenced_code_blocks(content)

        # Extract names from Interface & Class Hierarchy
        interface_names = self._extract_names_from_section("Interface & Class Hierarchy")
        # Extract names from Call Sites
        method_names = self._extract_names_from_section("Call Sites")

        all_names = interface_names + method_names

        for name in [n for n in all_names if len(n) >= self._MIN_NAME_LENGTH]:
            pattern = re.compile(r"\b" + re.escape(name) + r"\b")
            if not pattern.search(search_text):
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Researcher discovered '{name}' but it is not referenced "
                            f"in the plan (Implementation Steps, Testing Strategy, or Out of Scope)."
                        ),
                        suggestion=(
                            f"Ensure '{name}' is addressed in the plan or "
                            f"explicitly listed in Out of Scope."
                        ),
                    )
                )

        return findings


class TestCoverageValidator(Validator):
    """Check that every implementation file has a corresponding test entry."""

    # Match file paths in Implementation Steps (backtick-quoted, with extension)
    _PATH_RE = re.compile(r"`([^`\n]*?(?:/[^`\n]*?\.\w{1,8})[^`\n]*?)`")

    # Match NO_TEST_NEEDED opt-out markers
    _NO_TEST_NEEDED_RE = re.compile(r"<!--\s*NO_TEST_NEEDED:\s*.*?-->", re.IGNORECASE)

    # Paths to skip (not real file references)
    _SKIP_PATTERNS = _COMMON_SKIP_PATTERNS

    # Pattern source citations are references, not implementation files.
    # Matches "Pattern source: `path/to/file.py:10-20`" (whole line remainder).
    _PATTERN_SOURCE_PREFIX_RE = re.compile(
        r"Pattern\s+source:\s*[^\n]*$", re.IGNORECASE | re.MULTILINE
    )

    @property
    def name(self) -> str:
        return "Test Coverage"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        impl_text = _extract_plan_sections(content, ["Implementation Steps"])
        test_text = _extract_plan_sections(content, ["Testing Strategy"])

        if not impl_text or not test_text:
            return findings

        # Extract file paths from Implementation Steps (strip code blocks first)
        impl_stripped = _strip_fenced_code_blocks(impl_text)

        # Remove Pattern source citations so their paths aren't treated as impl files
        impl_cleaned = self._PATTERN_SOURCE_PREFIX_RE.sub("", impl_stripped)

        impl_paths: list[str] = []
        for m in self._PATH_RE.finditer(impl_cleaned):
            raw = m.group(1).strip(".,;:()\"' ")
            # Split off :line_number suffix
            if ":" in raw:
                parts = raw.rsplit(":", 1)
                if _LINE_SUFFIX_RE.match(parts[1]):
                    raw = parts[0]
            # Skip non-file references (URLs, placeholders, globs)
            if any(p.search(raw) for p in self._SKIP_PATTERNS):
                continue
            impl_paths.append(raw)

        # Check each impl file (skip test files themselves)
        test_section_lower = test_text.lower()
        for path in impl_paths:
            stem = (
                path.rsplit("/", 1)[-1].rsplit(".", 1)[0] if "/" in path else path.rsplit(".", 1)[0]
            )

            # Skip test files
            if stem.startswith("test_") or stem.endswith("_test") or stem.endswith("Test"):
                continue

            # Check if stem appears in Testing Strategy
            if stem.lower() in test_section_lower:
                continue

            # Check for NO_TEST_NEEDED opt-out mentioning this component
            opted_out = False
            for m in self._NO_TEST_NEEDED_RE.finditer(test_text):
                if stem.lower() in m.group(0).lower():
                    opted_out = True
                    break
            # Also check implementation section for opt-out
            if not opted_out:
                for m in self._NO_TEST_NEEDED_RE.finditer(impl_text):
                    if stem.lower() in m.group(0).lower():
                        opted_out = True
                        break
            if opted_out:
                continue

            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Implementation file `{path}` has no corresponding entry "
                        f"in Testing Strategy."
                    ),
                    suggestion=(
                        f"Add a test entry for `{path}` in the Testing Strategy section, "
                        f"or add `<!-- NO_TEST_NEEDED: {stem} - reason -->` to opt out."
                    ),
                )
            )

        return findings


class ImplementationDetailValidator(Validator):
    """Check that implementation steps include concrete detail."""

    # Detect code blocks (```)
    _CODE_BLOCK_RE = re.compile(r"```")
    # Detect inline method call chains (Class.method( or module.func()
    _METHOD_CALL_RE = re.compile(r"\w+\.\w+\(")
    # Detect TRIVIAL_STEP markers
    _TRIVIAL_STEP_RE = re.compile(r"<!--\s*TRIVIAL_STEP:", re.IGNORECASE)
    # Detect Pattern source citations
    _PATTERN_SOURCE_RE = re.compile(r"Pattern\s+source:", re.IGNORECASE)

    @property
    def name(self) -> str:
        return "Implementation Detail"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        impl_text = _extract_plan_sections(content, ["Implementation Steps"])
        if not impl_text:
            return findings

        # Split into numbered steps.
        # Pattern: newline followed by digits, dot, space. Sub-items like "1.1."
        # don't match because after the first "." comes a digit, not whitespace.
        steps = re.split(r"\n(?=\d+\.\s)", impl_text)

        for step in steps:
            step = step.strip()
            if not step:
                continue
            # Must start with a number (to be a real step)
            if not re.match(r"\d+\.\s", step):
                continue

            has_code_block = bool(self._CODE_BLOCK_RE.search(step))
            has_method_call = bool(self._METHOD_CALL_RE.search(step))
            has_trivial_marker = bool(self._TRIVIAL_STEP_RE.search(step))
            has_pattern_source = bool(self._PATTERN_SOURCE_RE.search(step))

            if (
                not has_code_block
                and not has_method_call
                and not has_trivial_marker
                and not has_pattern_source
            ):
                # Extract the step title (first line)
                first_line = step.split("\n")[0][:120]
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(f"Implementation step lacks concrete detail: '{first_line}'"),
                        suggestion=(
                            "Add a code snippet with `Pattern source:` citation, "
                            "an explicit method call chain (e.g., `Class.method(args)`), "
                            "or mark as `<!-- TRIVIAL_STEP: description -->`."
                        ),
                    )
                )

        return findings


class RiskCategoriesValidator(Validator):
    """Check that the Potential Risks section covers required categories."""

    @property
    def name(self) -> str:
        return "Risk Categories"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        risks_text = _extract_plan_sections(content, ["Potential Risks"])
        if not risks_text:
            return findings

        risks_lower = risks_text.lower()
        missing: list[str] = []

        # Group related categories — if either variant is present, consider covered
        category_groups = [
            (["external dependencies"], "External dependencies"),
            (["prerequisite work"], "Prerequisite work"),
            (["data integrity", "state management"], "Data integrity / state management"),
            (["startup", "cold-start", "cold start"], "Startup / cold-start behavior"),
            (["environment", "configuration drift"], "Environment / configuration drift"),
            (["performance", "scalability"], "Performance / scalability"),
            (["backward compatibility", "breaking change"], "Backward compatibility"),
        ]

        for keywords, label in category_groups:
            if not any(kw in risks_lower for kw in keywords):
                missing.append(label)

        if missing:
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.INFO,
                    message=(
                        f"Potential Risks section is missing categories: {', '.join(missing)}"
                    ),
                    suggestion=(
                        "Address each category explicitly, or write "
                        "'None identified' for categories that don't apply."
                    ),
                )
            )

        return findings


class CitationContentValidator(Validator):
    """Check that Pattern source citations match actual file content.

    For each ``Pattern source: file:line-line`` in the plan, reads the
    cited lines from disk and checks whether key identifiers from the
    adjacent code block appear in the cited range (>= 50% overlap).
    """

    _PATTERN_SOURCE_RE = re.compile(
        r"Pattern\s+source:\s*`?([^`\n]+?\.\w{1,8}):(\d+)(?:-(\d+))?`?",
        re.IGNORECASE,
    )

    _OVERLAP_THRESHOLD = 0.5

    @property
    def name(self) -> str:
        return "Citation Content"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        if context.repo_root is None:
            return []

        findings: list[ValidationFinding] = []
        lines = content.splitlines()
        line_index = _build_line_index(content)

        # Pre-parse all code blocks once (used to find the nearest block
        # for every citation instead of the old window-limited scan).
        code_blocks, _ = _extract_code_blocks(lines)

        for m in self._PATTERN_SOURCE_RE.finditer(content):
            file_path_str = m.group(1).strip()
            start_line = int(m.group(2))
            end_line = int(m.group(3)) if m.group(3) else start_line

            citation_line_num = _line_number_at(line_index, m.start())

            # Find adjacent code block (within 5 lines before or after)
            snippet_ids = self._extract_nearby_code_identifiers(
                lines, citation_line_num - 1, code_blocks
            )
            if not snippet_ids:
                continue  # No code block to verify against

            # Guard against path traversal
            abs_path = safe_resolve_path(context.repo_root, file_path_str)
            if abs_path is None:
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Pattern source path blocked (traversal): `{file_path_str}` "
                            f"(cited at line {citation_line_num})"
                        ),
                        line_number=citation_line_num,
                        suggestion="Use a relative path within the repository.",
                    )
                )
                continue

            # Read the actual file
            try:
                if not abs_path.is_file():
                    findings.append(
                        ValidationFinding(
                            validator_name=self.name,
                            severity=ValidationSeverity.WARNING,
                            message=(
                                f"Pattern source file not found: `{file_path_str}` "
                                f"(cited at line {citation_line_num})"
                            ),
                            line_number=citation_line_num,
                            suggestion="Verify the file path exists in the repository.",
                        )
                    )
                    continue

                try:
                    file_size = abs_path.stat().st_size
                except OSError:
                    continue
                if file_size > MAX_CITATION_FILE_SIZE:
                    findings.append(
                        ValidationFinding(
                            validator_name=self.name,
                            severity=ValidationSeverity.INFO,
                            message=(
                                f"Skipping oversized file: `{file_path_str}` "
                                f"({file_size // 1024 // 1024} MB, cited at line {citation_line_num})"
                            ),
                            line_number=citation_line_num,
                            suggestion="Large files are skipped to avoid memory issues.",
                        )
                    )
                    continue

                file_lines = abs_path.read_text(errors="replace").splitlines()
                range_start = max(0, start_line - 1)
                range_end = min(len(file_lines), end_line)

                if range_start >= len(file_lines):
                    findings.append(
                        ValidationFinding(
                            validator_name=self.name,
                            severity=ValidationSeverity.WARNING,
                            message=(
                                f"Pattern source line range {start_line}-{end_line} "
                                f"out of bounds for `{file_path_str}` "
                                f"({len(file_lines)} lines, cited at line {citation_line_num})"
                            ),
                            line_number=citation_line_num,
                            suggestion="Verify the line range matches the file.",
                        )
                    )
                    continue

                cited_text = "\n".join(file_lines[range_start:range_end])
                found_ids = set(IDENTIFIER_RE.findall(cited_text))

                overlap = snippet_ids & found_ids
                ratio = len(overlap) / len(snippet_ids) if snippet_ids else 1.0

                if ratio < self._OVERLAP_THRESHOLD:
                    findings.append(
                        ValidationFinding(
                            validator_name=self.name,
                            severity=ValidationSeverity.WARNING,
                            message=(
                                f"Pattern source citation mismatch at line {citation_line_num}: "
                                f"`{file_path_str}:{start_line}-{end_line}` — "
                                f"only {len(overlap)}/{len(snippet_ids)} snippet identifiers "
                                f"found in cited range"
                            ),
                            line_number=citation_line_num,
                            suggestion=(
                                "Verify the code snippet matches the cited file. "
                                "The pattern may reference the wrong file or line range."
                            ),
                        )
                    )

            except OSError:
                continue  # Non-blocking

        return findings

    @staticmethod
    def _extract_nearby_code_identifiers(
        lines: list[str],
        citation_idx: int,
        code_blocks: list[tuple[int, int]],
    ) -> set[str]:
        """Extract identifiers from the nearest code block (within 5 lines).

        Uses the pre-parsed *code_blocks* list so that long code blocks
        (whose closing fence is far from the citation) are still found.
        """
        best_block = find_nearest_code_block(citation_idx, code_blocks)
        if best_block is None:
            return set()

        snippet_text = "\n".join(lines[best_block[0] + 1 : best_block[1]])
        return set(IDENTIFIER_RE.findall(snippet_text))


class RegistrationIdempotencyValidator(Validator):
    """Detect duplicate component registration anti-patterns in code snippets.

    Catches cases where the plan proposes both annotation-based and
    explicit registration for the same class (e.g., ``@Component`` +
    ``@Bean`` method returning the same type).
    """

    # Annotation-based registration markers (language-agnostic)
    _ANNOTATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        (
            "Spring @Component family",
            re.compile(r"@(?:Component|Service|Repository|Controller|RestController)\b"),
        ),
        ("Angular @Injectable", re.compile(r"@Injectable\b")),
        (
            "CDI @ApplicationScoped family",
            re.compile(r"@(?:ApplicationScoped|RequestScoped|SessionScoped|Dependent)\b"),
        ),
    ]

    # Explicit registration markers
    _EXPLICIT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("Spring @Bean", re.compile(r"@Bean\b")),
        ("Angular provide()", re.compile(r"\bprovide\s*\(")),
        ("CDI @Produces", re.compile(r"@Produces\b")),
    ]

    # Regex to extract class name following an annotation-based registration marker.
    # Bridges up to ~200 chars between the annotation and the class keyword so that
    # intermediate annotations/modifiers (e.g. @Scope, public, abstract) don't break
    # the match.
    _ANNOTATION_CLASS_RE = re.compile(
        r"@(?:Component|Service|Repository|Controller|RestController|Injectable"
        r"|ApplicationScoped|RequestScoped|SessionScoped|Dependent)\b"
        r"[\s\S]{0,200}?\bclass\s+(\w+)"
    )

    # Regex to extract the return type of a @Bean / @Produces method.
    # Allows intermediate annotations (@Scope, @Primary, etc.) between @Bean
    # and the method signature.  Acceptable as a heuristic for plan-level validation.
    _BEAN_RETURN_TYPE_RE = re.compile(
        r"@(?:Bean|Produces)\b(?:\s*\([^)]*\))?"
        r"(?:\s*@\w+(?:\([^)]*\))?)*"
        r"\s*(?:(?:public|protected|private|static|final|abstract|synchronized)\s+)*"
        r"(\w+)\s+\w+\s*\("
    )

    # Suffixes commonly used for implementation classes.
    _IMPL_SUFFIXES = ("Impl", "Adapter", "Decorator", "Proxy")

    @staticmethod
    def _normalize_class_name(name: str) -> str:
        """Strip implementation prefixes/suffixes for fuzzy interface-vs-impl matching.

        Prefix stripping is applied first so that e.g. ``DefaultAdapter`` →
        ``Adapter`` (not ``Default`` via suffix-first ordering).
        """
        # Prefix: "Default" (e.g. DefaultMyService → MyService)
        if name.startswith("Default") and len(name) > len("Default"):
            name = name[len("Default") :]
        for suffix in RegistrationIdempotencyValidator._IMPL_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                return name[: -len(suffix)]
        return name

    @property
    def name(self) -> str:
        return "Registration Idempotency"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        lines = content.splitlines()

        code_blocks, _ = _extract_code_blocks(lines)

        # Phase 1: per-block dual registration (existing logic)
        # Also collect per-block class sets for cross-block Phase 2.
        per_block_annotation: list[set[str]] = []
        per_block_explicit: list[set[str]] = []

        for block_open, block_close in code_blocks:
            block_text = "\n".join(lines[block_open + 1 : block_close])
            if len(block_text.strip()) < 10:
                # Always append (even empty sets) to keep indices aligned
                # with code_blocks for Phase 2 cross-block correlation.
                per_block_annotation.append(set())
                per_block_explicit.append(set())
                continue

            # Check for annotation-based registration
            annotation_matches: list[str] = []
            for label, pattern in self._ANNOTATION_PATTERNS:
                if pattern.search(block_text):
                    annotation_matches.append(label)

            # Check for explicit registration
            explicit_matches: list[str] = []
            for label, pattern in self._EXPLICIT_PATTERNS:
                if pattern.search(block_text):
                    explicit_matches.append(label)

            # Flag if both annotation AND explicit registration found in same block
            if annotation_matches and explicit_matches:
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Potential dual registration at line {block_open + 1}: "
                            f"code block uses both {annotation_matches[0]} and "
                            f"{explicit_matches[0]}. This may cause double "
                            f"registration at runtime."
                        ),
                        line_number=block_open + 1,
                        suggestion=(
                            "Use either annotation-based registration OR explicit "
                            "registration, not both. Remove one to avoid duplicate "
                            "bean/component registration."
                        ),
                    )
                )

            # Collect class names per block for cross-block Phase 2
            block_ann: set[str] = set()
            for m in self._ANNOTATION_CLASS_RE.finditer(block_text):
                block_ann.add(m.group(1))
            block_exp: set[str] = set()
            for m in self._BEAN_RETURN_TYPE_RE.finditer(block_text):
                block_exp.add(m.group(1))

            per_block_annotation.append(block_ann)
            per_block_explicit.append(block_exp)

        # Phase 2: cross-block correlation — same class annotated in one
        # block and explicitly registered in a DIFFERENT block.
        # Use normalized names to catch interface-vs-impl mismatches
        # (e.g. @Component MyServiceImpl + @Bean MyService).
        norm_ann: dict[str, set[str]] = {}  # norm_key -> original names
        norm_exp: dict[str, set[str]] = {}
        ann_block_map: dict[str, set[int]] = {}  # norm_key -> block indices
        exp_block_map: dict[str, set[int]] = {}

        for idx, ann_set in enumerate(per_block_annotation):
            for cls_name in ann_set:
                nk = self._normalize_class_name(cls_name)
                norm_ann.setdefault(nk, set()).add(cls_name)
                ann_block_map.setdefault(nk, set()).add(idx)

        for idx, exp_set in enumerate(per_block_explicit):
            for cls_name in exp_set:
                nk = self._normalize_class_name(cls_name)
                norm_exp.setdefault(nk, set()).add(cls_name)
                exp_block_map.setdefault(nk, set()).add(idx)

        # Only flag classes that appear in DIFFERENT blocks
        cross_block_norm_keys = set(norm_ann) & set(norm_exp)
        truly_cross_block: set[str] = set()
        for nk in cross_block_norm_keys:
            if ann_block_map[nk] != exp_block_map[nk]:
                # Report the original class names for clarity
                truly_cross_block |= norm_ann[nk] | norm_exp[nk]

        if truly_cross_block:
            cls_list = ", ".join(sorted(truly_cross_block))
            # Report the earliest involved code block's line number.
            involved_block_indices: set[int] = set()
            for nk in cross_block_norm_keys:
                if ann_block_map[nk] != exp_block_map[nk]:
                    involved_block_indices |= ann_block_map[nk] | exp_block_map[nk]
            earliest_line = (
                min(code_blocks[bi][0] + 1 for bi in involved_block_indices)
                if involved_block_indices
                else 0
            )
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Potential cross-block dual registration for: {cls_list}. "
                        f"Class appears with annotation-based registration in one "
                        f"code block and explicit @Bean/@Produces in another."
                    ),
                    line_number=earliest_line,
                    suggestion=(
                        "Use either annotation-based registration OR explicit "
                        "registration, not both. Remove one to avoid duplicate "
                        "bean/component registration."
                    ),
                )
            )

        return findings


class SnippetCompletenessValidator(Validator):
    """Detect incomplete code snippets — fields without constructors/init.

    Checks code blocks for field declarations that lack constructor or
    initialization method. Helps catch snippets that show member
    variables but omit how they are set up.
    """

    # Detect field declarations (Java/Kotlin/C#/TypeScript)
    _FIELD_PATTERNS = [
        re.compile(  # Java: annotations, generics, arrays — private final List<String> foo;
            r"(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:private|protected)\s+(?:final\s+)?"
            r"[\w.]+(?:<[\w.,\s<>?]+>)?(?:\[\])?"
            r"\s+\w+\s*;"
        ),
        re.compile(r"private\s+\w+:\s*\w+"),  # TypeScript: private foo: Foo
        re.compile(r"self\.\w+\s*="),  # Python: self.foo =
        re.compile(r"val\s+\w+:\s*\w+"),  # Kotlin: val foo: Foo
    ]

    # Detect constructor/init declarations (or patterns that make explicit init unnecessary)
    _INIT_PATTERNS = [
        re.compile(r"(?:public|protected|private)\s+\w+\s*\("),  # Java/C# constructor
        re.compile(r"def\s+__init__\s*\("),  # Python __init__
        re.compile(r"constructor\s*\("),  # TypeScript/Kotlin constructor
        re.compile(r"init\s*\{"),  # Kotlin init block
        re.compile(r"@(?:Autowired|Inject)\b"),  # Spring/CDI injection
        re.compile(r"@dataclass"),  # Python dataclass (generates __init__)
        re.compile(
            r"class\s+\w+\(.*(?:BaseModel|NamedTuple|TypedDict)\s*[),]"
        ),  # Pydantic/typing (no explicit __init__ needed)
    ]

    @property
    def name(self) -> str:
        return "Snippet Completeness"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        lines = content.splitlines()

        code_blocks, _ = _extract_code_blocks(lines)

        for block_open, block_close in code_blocks:
            block_text = "\n".join(lines[block_open + 1 : block_close])
            if len(block_text.strip()) < 20:
                continue

            has_fields = any(p.search(block_text) for p in self._FIELD_PATTERNS)
            has_init = any(p.search(block_text) for p in self._INIT_PATTERNS)

            if has_fields and not has_init:
                findings.append(
                    ValidationFinding(
                        validator_name=self.name,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Code snippet at line {block_open + 1} declares fields "
                            f"but has no constructor/initialization method."
                        ),
                        line_number=block_open + 1,
                        suggestion=(
                            "Add a constructor or initialization method showing "
                            "how the fields are set up, or note that injection "
                            "is handled by the framework."
                        ),
                    )
                )

        return findings


class OperationalCompletenessValidator(Validator):
    """Check that metric/alert plans include operational completeness.

    When the plan mentions metrics, alerts, or monitoring, checks for
    operational elements: query examples, thresholds, escalation paths.
    """

    # Detect metrics/alert related content
    _METRIC_KEYWORDS = re.compile(
        r"\b(?:metric|alert|monitor|gauge|counter|histogram|prometheus|grafana|"
        r"datadog|threshold|SLO|SLI|SLA|dashboard|runbook|pagerduty|opsgenie)\b",
        re.IGNORECASE,
    )

    # Operational elements to check for
    _OPERATIONAL_ELEMENTS = [
        (
            "query example",
            re.compile(
                r"(?:query|PromQL|promql|SELECT|select|WHERE|where)\b.*[{(]",
                re.IGNORECASE,
            ),
        ),
        (
            "threshold value",
            re.compile(
                r"(?:threshold\s*(?:[:=]|of|is|at)?\s*(?:[><=]+\s*)?\d+"
                r"|(?:alert|metric|sla|slo|latency|error[-_.]?rate|cpu|memory|disk|queue)"
                r"\w*\s*(?:>|<|>=|<=)\s*\d+)",
                re.IGNORECASE,
            ),
        ),
        (
            "escalation reference",
            re.compile(
                r"\b(?:escalat|runbook|playbook|on-?call|page|alert\s+(?:route|channel|team))\b",
                re.IGNORECASE,
            ),
        ),
    ]

    @property
    def name(self) -> str:
        return "Operational Completeness"

    # Signal categories that elevate severity from INFO to WARNING
    _ELEVATED_SIGNALS = {"metric", "alert", "monitor"}

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        # Only activate if plan mentions metrics/alerts
        if not self._METRIC_KEYWORDS.search(content):
            return []

        findings: list[ValidationFinding] = []
        missing_elements: list[str] = []

        for element_name, pattern in self._OPERATIONAL_ELEMENTS:
            if not pattern.search(content):
                missing_elements.append(element_name)

        # Elevate severity when ticket signals indicate this is a metrics/alert ticket
        has_signal = bool(self._ELEVATED_SIGNALS & set(context.ticket_signals))
        severity = ValidationSeverity.WARNING if has_signal else ValidationSeverity.INFO

        if missing_elements:
            findings.append(
                ValidationFinding(
                    validator_name=self.name,
                    severity=severity,
                    message=(
                        f"Plan includes metrics/alerts but is missing operational elements: "
                        f"{', '.join(missing_elements)}"
                    ),
                    suggestion=(
                        "Consider adding: example queries for validating metrics, "
                        "specific threshold values, and escalation/runbook references."
                    ),
                )
            )

        return findings


class NamingConsistencyValidator(Validator):
    """Check cross-format naming consistency for identifiers.

    Groups backtick-quoted identifiers by normalized form (replacing
    dots, underscores, hyphens) and warns when the same logical
    identifier uses inconsistent separators.
    """

    # Extract backtick-quoted identifiers that look like config keys or metric names
    _IDENTIFIER_RE = re.compile(r"`([a-zA-Z][\w.*-]{3,})`")

    # Separators to normalize
    _SEPARATOR_RE = re.compile(r"[._-]")

    @property
    def name(self) -> str:
        return "Naming Consistency"

    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        # Strip code blocks to avoid false positives from code
        stripped = _strip_fenced_code_blocks(content)

        # Group identifiers by normalized form
        groups: dict[str, set[str]] = {}
        for m in self._IDENTIFIER_RE.finditer(stripped):
            identifier = m.group(1)
            # Skip file paths (contain /)
            if "/" in identifier:
                continue
            # Skip very long identifiers (likely not naming issues)
            if len(identifier) > 80:
                continue

            normalized = self._SEPARATOR_RE.sub("", identifier).lower()
            if normalized not in groups:
                groups[normalized] = set()
            groups[normalized].add(identifier)

        # Warn on groups with inconsistent separators
        for _normalized, variants in groups.items():
            if len(variants) > 1:
                # Check if variants use different separators
                separator_types: set[str] = set()
                for v in variants:
                    if "." in v:
                        separator_types.add("dot")
                    if "_" in v:
                        separator_types.add("underscore")
                    if "-" in v:
                        separator_types.add("hyphen")

                if len(separator_types) > 1:
                    variant_list = ", ".join(f"`{v}`" for v in sorted(variants))
                    findings.append(
                        ValidationFinding(
                            validator_name=self.name,
                            severity=ValidationSeverity.WARNING,
                            message=(
                                f"Inconsistent naming separators: {variant_list} "
                                f"(uses {' and '.join(sorted(separator_types))})"
                            ),
                            suggestion=(
                                "Document the naming convention for each format "
                                "(e.g., dots for Java properties, underscores for "
                                "environment variables, hyphens for YAML keys)."
                            ),
                        )
                    )

        return findings


def create_plan_validator_registry(
    researcher_output: str = "",
) -> ValidatorRegistry:
    """Create the default plan validator registry with all standard gates.

    Args:
        researcher_output: Raw researcher output, passed to DiscoveryCoverageValidator.
    """
    registry = ValidatorRegistry()
    registry.register(RequiredSectionsValidator())
    registry.register(FileExistsValidator())
    registry.register(PatternSourceValidator())
    registry.register(UnresolvedMarkersValidator())
    registry.register(DiscoveryCoverageValidator(researcher_output))
    registry.register(TestCoverageValidator())
    registry.register(ImplementationDetailValidator())
    registry.register(RiskCategoriesValidator())
    # New validators (Phase 1)
    registry.register(CitationContentValidator())
    registry.register(RegistrationIdempotencyValidator())
    # New validators (Phase 2)
    registry.register(SnippetCompletenessValidator())
    registry.register(OperationalCompletenessValidator())
    registry.register(NamingConsistencyValidator())
    return registry


__all__ = [
    "NEW_FILE_MARKER_RE",
    "UNVERIFIED_RE",
    "RequiredSectionsValidator",
    "FileExistsValidator",
    "PatternSourceValidator",
    "UnresolvedMarkersValidator",
    "DiscoveryCoverageValidator",
    "TestCoverageValidator",
    "ImplementationDetailValidator",
    "RiskCategoriesValidator",
    "CitationContentValidator",
    "RegistrationIdempotencyValidator",
    "SnippetCompletenessValidator",
    "OperationalCompletenessValidator",
    "NamingConsistencyValidator",
    "create_plan_validator_registry",
]
