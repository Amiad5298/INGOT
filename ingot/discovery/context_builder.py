"""Orchestrate local discovery tools into a structured report.

:class:`ContextBuilder` runs all local discovery tools (FileIndex,
GrepEngine, ManifestParser, TestMapper) and produces a
:class:`LocalDiscoveryReport` that can be injected into AI prompts
as deterministically verified context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ingot.discovery.file_index import FileIndex
from ingot.discovery.grep_engine import GrepEngine, GrepMatch
from ingot.discovery.manifest_parser import ManifestParser, ModuleGraph
from ingot.discovery.test_mapper import TestMapper
from ingot.utils.logging import log_message

# Default budget for the markdown report (characters).
_DEFAULT_REPORT_BUDGET = 8000

# Maximum keywords to extract from ticket text.
_MAX_KEYWORDS = 20

# File count threshold above which GrepEngine is scoped to relevant dirs only.
_LARGE_REPO_THRESHOLD = 50_000

# Regex for extracting likely identifiers from ticket text.
_KEYWORD_RE = re.compile(
    r"(?:"
    r"[A-Z][a-zA-Z0-9]{3,}"  # PascalCase: FooService, MetricsHelper
    r"|[a-z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+"  # camelCase: checkAndAlert
    r"|[a-z]+(?:_[a-z]+)+"  # snake_case: register_metric, check_status
    r"|[a-z_]{2,}\.[a-z_]{2,}"  # dotted: some.config.key
    r"|[A-Z][A-Z0-9]{1,5}(?=[^a-zA-Z]|$)"  # ACRONYMS: AWS, S3, EC2, SQS (2-6 chars)
    r")"
)

# All-caps English words to filter from acronym matches.
_ACRONYM_STOPWORDS: frozenset[str] = frozenset(
    {
        "THE",
        "AND",
        "FOR",
        "BUT",
        "NOT",
        "ARE",
        "WAS",
        "ALL",
        "ANY",
        "CAN",
        "HAS",
        "HER",
        "HIS",
        "HOW",
        "ITS",
        "MAY",
        "NEW",
        "NOW",
        "OLD",
        "SEE",
        "WAY",
        "WHO",
        "DID",
        "GET",
        "HIM",
        "LET",
        "SAY",
        "SHE",
        "TOO",
        "USE",
        "ADD",
        "END",
        "FEW",
        "GOT",
        "HAD",
        "SET",
        "TOP",
        "TRY",
        "TWO",
        "YET",
        "FIX",
        "BUG",
        "RUN",
        "PUT",
    }
)


@dataclass
class LocalDiscoveryReport:
    """Structured output from local codebase discovery."""

    file_index: FileIndex | None = None
    keyword_matches: dict[str, list[GrepMatch]] = field(default_factory=dict)
    module_graph: ModuleGraph | None = None
    test_mappings: dict[str, list[PurePosixPath]] = field(default_factory=dict)
    keywords_used: list[str] = field(default_factory=list)
    was_truncated: bool = False
    truncation_reasons: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Check if the report has any useful content."""
        return (
            not self.keyword_matches
            and (self.module_graph is None or not self.module_graph.modules)
            and not self.test_mappings
        )

    def to_markdown(self, budget: int = _DEFAULT_REPORT_BUDGET) -> str:
        """Format the report as markdown for prompt injection.

        Truncates to stay within ``budget`` characters.
        """
        sections: list[str] = []

        # Module graph
        if self.module_graph and self.module_graph.modules:
            sections.append("#### Module Structure\n" + self.module_graph.to_markdown())

        # Keyword matches (grouped by keyword)
        if self.keyword_matches:
            kw_lines = ["#### Keyword Matches"]
            for kw, matches in self.keyword_matches.items():
                if not matches:
                    continue
                kw_lines.append(
                    f"**`{kw}`** ({len(matches)} match{'es' if len(matches) != 1 else ''}):"
                )
                for m in matches[:5]:  # Cap at 5 per keyword
                    kw_lines.append(f"  - `{m.file}:{m.line_num}` — {m.line_content.strip()[:120]}")
                if len(matches) > 5:
                    kw_lines.append(f"  - ... and {len(matches) - 5} more")
            sections.append("\n".join(kw_lines))

        # Test mappings
        if self.test_mappings:
            test_lines = ["#### Test File Mappings"]
            for src, tests in self.test_mappings.items():
                test_paths = ", ".join(f"`{t}`" for t in tests[:3])
                test_lines.append(f"  - `{src}` → {test_paths}")
            sections.append("\n".join(test_lines))

        # Truncation warning
        if self.was_truncated and self.truncation_reasons:
            reasons = ", ".join(sorted(self.truncation_reasons))
            sections.append(
                f"> **Note**: Search results were truncated ({reasons}). "
                f"Some matches may be missing."
            )

        if not sections:
            return ""

        report = "\n\n".join(sections)

        # Truncate if needed.  len(report) is a character count (Python 3 str),
        # not a byte count, so slicing cannot split a Unicode code point.
        # rfind("\n") ensures the cut lands on a clean line boundary.
        if len(report) > budget:
            cut = report.rfind("\n", 0, budget - 20)
            if cut < 0:
                cut = budget - 20
            report = report[:cut] + "\n\n... [truncated]"

        return report


_STOPWORDS: frozenset[str] = frozenset(
    {
        "this",
        "that",
        "when",
        "then",
        "with",
        "from",
        "some",
        "note",
        "todo",
        "each",
        "also",
        "only",
        "will",
        "must",
        "have",
        "been",
        "does",
        "more",
        "most",
        "just",
        "very",
    }
)


def extract_keywords(text: str, max_keywords: int = _MAX_KEYWORDS) -> list[str]:
    """Extract likely code identifiers from ticket text.

    Args:
        text: Ticket title + description.
        max_keywords: Maximum number of keywords to return.

    Returns:
        Deduplicated list of keyword strings.
    """
    if not text:
        return []

    matches = _KEYWORD_RE.findall(text)

    # Deduplicate preserving order, filtering stopwords
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m.lower() in _STOPWORDS:
            continue
        if m.isupper() and m in _ACRONYM_STOPWORDS:
            continue
        if m.lower() not in seen:
            seen.add(m.lower())
            result.append(m)
            if len(result) >= max_keywords:
                break

    return result


class ContextBuilder:
    """Orchestrate local discovery tools into a structured report.

    Args:
        repo_root: Absolute path to the repository root.
        max_report_budget: Character budget for the markdown report.
    """

    def __init__(
        self,
        repo_root: Path,
        *,
        max_report_budget: int = _DEFAULT_REPORT_BUDGET,
        grep_max_per_file: int = 5,
        grep_max_total: int = 100,
        grep_timeout: float = 30.0,
        large_repo_threshold: int = _LARGE_REPO_THRESHOLD,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._budget = max_report_budget
        self._grep_max_per_file = grep_max_per_file
        self._grep_max_total = grep_max_total
        self._grep_timeout = grep_timeout
        self._large_repo_threshold = large_repo_threshold

    def build(
        self,
        keywords: list[str] | None = None,
        file_index: FileIndex | None = None,
    ) -> LocalDiscoveryReport:
        """Run all discovery tools and produce a report.

        Args:
            keywords: Code identifiers to search for (from ticket text).
            file_index: Pre-built FileIndex (avoids rebuilding).

        Returns:
            LocalDiscoveryReport with all discovered facts.
        """
        report = LocalDiscoveryReport()

        # Step 1: Build or reuse FileIndex
        if file_index is None:
            try:
                file_index = FileIndex(self._repo_root)
            except Exception as exc:
                log_message(f"ContextBuilder: FileIndex build failed: {exc}")
                return report

        report.file_index = file_index

        if file_index.file_count == 0:
            log_message("ContextBuilder: empty FileIndex, skipping discovery")
            return report

        # Step 2: Parse build manifests
        try:
            parser = ManifestParser(self._repo_root)
            report.module_graph = parser.parse()
        except Exception as exc:
            log_message(f"ContextBuilder: ManifestParser failed: {exc}")

        # Step 3: Grep for keywords
        if keywords:
            report.keywords_used = keywords
            try:
                # For large repos, limit search scope to reduce search time
                search_paths = file_index.all_paths()
                if file_index.file_count > self._large_repo_threshold:
                    search_paths = self._scope_paths_for_large_repo(file_index, keywords)
                    log_message(
                        f"ContextBuilder: large repo ({file_index.file_count} files), "
                        f"scoped search to {len(search_paths)} files"
                    )

                engine = GrepEngine(
                    self._repo_root,
                    search_paths,
                    context_lines=0,
                    max_matches_per_file=self._grep_max_per_file,
                    max_matches_total=self._grep_max_total,
                    search_timeout=self._grep_timeout,
                )
                escaped_keywords = [re.escape(kw) for kw in keywords]
                batch_results = engine.search_batch_with_meta(
                    escaped_keywords,
                    ignore_case=False,
                )
                # Map back to original keywords (search_batch used escaped patterns)
                original_matches: dict[str, list[GrepMatch]] = {}
                for kw, escaped in zip(keywords, escaped_keywords, strict=True):
                    sr = batch_results.get(escaped)
                    if sr is not None:
                        original_matches[kw] = sr.matches
                        if sr.meta.was_truncated:
                            report.was_truncated = True
                            if (
                                sr.meta.truncation_reason
                                and sr.meta.truncation_reason not in report.truncation_reasons
                            ):
                                report.truncation_reasons.append(sr.meta.truncation_reason)
                    else:
                        original_matches[kw] = []
                report.keyword_matches = original_matches
            except Exception as exc:
                log_message(f"ContextBuilder: GrepEngine failed: {exc}")

        # Step 4: Map source files to test files
        if report.keyword_matches:
            try:
                mapper = TestMapper(file_index)
                # Collect unique source files from grep matches
                source_files: set[str] = set()
                for matches in report.keyword_matches.values():
                    for m in matches:
                        source_files.add(str(m.file))

                report.test_mappings = mapper.map_all(list(source_files))
            except Exception as exc:
                log_message(f"ContextBuilder: TestMapper failed: {exc}")

        total_matches = sum(len(v) for v in report.keyword_matches.values())
        log_message(
            f"ContextBuilder: completed — "
            f"{len(report.keywords_used)} keywords, "
            f"{total_matches} matches, "
            f"{len(report.test_mappings)} test mappings"
        )

        return report

    @staticmethod
    def _scope_paths_for_large_repo(
        file_index: FileIndex,
        keywords: list[str],
    ) -> list[PurePosixPath]:
        """Limit search scope for large repos by collecting keyword-related paths.

        Collects files whose stem matches any keyword (case-insensitive)
        plus all files in the same directories. Falls back to all paths
        if scoping produces nothing.
        """
        # Collect paths whose stem matches any keyword exactly (case-insensitive
        # exact match is handled by FileIndex.find_by_stem).
        relevant_dirs: set[str] = set()
        all_paths = file_index.all_paths()

        for kw in keywords:
            kw_lower = kw.lower()
            for p in file_index.find_by_stem(kw_lower):
                relevant_dirs.add(str(p.parent))

        if not relevant_dirs:
            return all_paths

        # Include all files in those directories (and one level up)
        expanded_dirs: set[str] = set()
        for d in relevant_dirs:
            expanded_dirs.add(d)
            parent = str(PurePosixPath(d).parent)
            if parent != ".":
                expanded_dirs.add(parent)

        scoped = [p for p in all_paths if str(p.parent) in expanded_dirs]
        return scoped if scoped else all_paths


__all__ = ["ContextBuilder", "LocalDiscoveryReport", "extract_keywords"]
