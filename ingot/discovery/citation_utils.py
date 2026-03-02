"""Shared utilities for citation verification across discovery and validation.

Provides path-safety checks and a canonical identifier regex used by
both :class:`CitationVerifier` and :class:`CitationContentValidator`.

Note: The ``Source:`` and ``Pattern source:`` citation regexes live in their
respective validator classes — only :data:`IDENTIFIER_RE` is shared here.
"""

from __future__ import annotations

import re
from pathlib import Path

# Maximum file size (bytes) that citation verifiers will read.
MAX_CITATION_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Number of lines to search around a citation for an adjacent code block.
CODE_BLOCK_SEARCH_WINDOW = 5

# Canonical identifier regex shared between CitationVerifier and
# CitationContentValidator.  Uses lookahead for method calls so the
# extracted text does NOT include the trailing '('.
IDENTIFIER_RE = re.compile(
    r"(?:"
    r"@[A-Z]\w+"  # Annotations: @Component, @Bean
    r"|[A-Z][a-zA-Z0-9]{2,}"  # PascalCase: Foo, DistributionSummary (3+ chars)
    r"|\w+\.\w+(?=\()"  # Method calls: builder.register( — lookahead excludes '('
    r"|[a-z_]\w{2,}(?=\()"  # Function calls: register_metric(
    r")"
)

# Common short English words that happen to match PascalCase (3+ chars starting
# with uppercase).  Filtering these reduces false-positive identifiers in prose.
_PASCAL_STOPWORDS: frozenset[str] = frozenset(
    {
        "The",
        "This",
        "That",
        "And",
        "But",
        "For",
        "Not",
        "All",
        "Any",
        "Can",
        "Did",
        "Get",
        "Has",
        "Her",
        "Him",
        "His",
        "How",
        "Its",
        "Let",
        "May",
        "New",
        "Now",
        "Old",
        "One",
        "Our",
        "Out",
        "Own",
        "Say",
        "She",
        "Too",
        "Use",
        "Was",
        "Who",
        "Why",
        "Yet",
    }
)


def extract_identifiers(text: str) -> set[str]:
    """Extract code identifiers from *text* using :data:`IDENTIFIER_RE`.

    Filters out common English words that happen to match PascalCase.
    """
    return {m for m in IDENTIFIER_RE.findall(text) if m not in _PASCAL_STOPWORDS}


def safe_resolve_path(repo_root: Path, file_path: str) -> Path | None:
    """Safely resolve *file_path* relative to *repo_root*.

    Returns ``None`` (and therefore blocks the read) when:
    - *file_path* is absolute,
    - the resolved result escapes *repo_root* (e.g. ``../../etc/passwd``),
    - the path contains a null byte.

    Symlinks are resolved before the containment check.

    Note: there is an inherent TOCTOU race between ``resolve()`` and the
    caller's subsequent read — a symlink target could change in between.
    This is acceptable for plan-validation purposes.
    """
    if not file_path or "\x00" in file_path:
        return None

    # Reject absolute paths outright
    if file_path.startswith("/") or file_path.startswith("\\"):
        return None

    try:
        resolved_root = repo_root.resolve()
        candidate = (resolved_root / file_path).resolve()
        if not candidate.is_relative_to(resolved_root):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def find_nearest_code_block(
    citation_idx: int,
    code_blocks: list[tuple[int, int]],
    max_distance: int = CODE_BLOCK_SEARCH_WINDOW,
) -> tuple[int, int] | None:
    """Find the nearest fenced code block within *max_distance* lines.

    Distance is measured as the gap between *citation_idx* and the nearest
    boundary of each block.  A citation **inside** a block has distance 0.

    Returns:
        ``(open_line, close_line)`` of the nearest block, or ``None``.
    """
    best_block: tuple[int, int] | None = None
    best_distance = float("inf")
    for block_open, block_close in code_blocks:
        if block_open <= citation_idx <= block_close:
            distance = 0
        elif citation_idx < block_open:
            distance = block_open - citation_idx
        else:
            distance = citation_idx - block_close

        if distance <= max_distance and distance < best_distance:
            best_distance = distance
            best_block = (block_open, block_close)
    return best_block


__all__ = [
    "CODE_BLOCK_SEARCH_WINDOW",
    "IDENTIFIER_RE",
    "MAX_CITATION_FILE_SIZE",
    "extract_identifiers",
    "find_nearest_code_block",
    "safe_resolve_path",
]
