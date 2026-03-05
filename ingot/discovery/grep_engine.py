"""Python-native regex search across indexed repository files.

Provides deterministic, local grep capabilities without external
dependencies (no ripgrep/grep subprocess). Uses the :class:`FileIndex`
as its file list source.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ingot.utils.logging import log_message


@dataclass(frozen=True)
class GrepMatch:
    """A single search match result."""

    file: PurePosixPath
    line_num: int
    line_content: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchMeta:
    """Metadata about a search operation."""

    total_matches_found: int
    files_searched: int
    files_total: int
    was_truncated: bool
    truncation_reason: str | None = None  # "max_total" | "timeout"


@dataclass(frozen=True)
class SearchResult:
    """Search results with metadata."""

    matches: list[GrepMatch]
    meta: SearchMeta


# Default limits
_DEFAULT_MAX_MATCHES_PER_FILE = 50
_DEFAULT_MAX_MATCHES_TOTAL = 500
_DEFAULT_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_DEFAULT_SEARCH_TIMEOUT = 30.0  # seconds
_DEFAULT_MAX_LINE_LENGTH = 10_000


class GrepEngine:
    """Python-native regex search across a set of repository files.

    Args:
        repo_root: Absolute path to the repository root.
        file_paths: List of relative paths to search (typically from FileIndex).
        context_lines: Number of context lines before/after each match.
        max_matches_per_file: Stop searching a file after this many matches.
        max_matches_total: Stop searching entirely after this many matches.
        max_file_size: Skip files larger than this (bytes).
    """

    def __init__(
        self,
        repo_root: Path,
        file_paths: list[PurePosixPath],
        *,
        context_lines: int = 0,
        max_matches_per_file: int = _DEFAULT_MAX_MATCHES_PER_FILE,
        max_matches_total: int = _DEFAULT_MAX_MATCHES_TOTAL,
        max_file_size: int = _DEFAULT_MAX_FILE_SIZE,
        search_timeout: float = _DEFAULT_SEARCH_TIMEOUT,
        max_line_length: int = _DEFAULT_MAX_LINE_LENGTH,
    ) -> None:
        self._repo_root = repo_root.resolve()
        self._file_paths = file_paths
        self._context_lines = context_lines
        self._max_per_file = max_matches_per_file
        self._max_total = max_matches_total
        self._max_file_size = max_file_size
        self._search_timeout = search_timeout
        self._max_line_length = max_line_length
        # Pattern-keyed result cache (session-scoped)
        self._cache: dict[tuple[str, bool], SearchResult] = {}

    def search(self, pattern: str, *, ignore_case: bool = False) -> list[GrepMatch]:
        """Search all indexed files for a single regex pattern.

        Results are cached by ``(pattern, ignore_case)`` key for the
        lifetime of this engine instance.

        Args:
            pattern: Regular expression to search for.
            ignore_case: If True, perform case-insensitive matching.

        Returns:
            List of :class:`GrepMatch` results.
        """
        return self.search_with_meta(pattern, ignore_case=ignore_case).matches

    def search_with_meta(self, pattern: str, *, ignore_case: bool = False) -> SearchResult:
        """Search all indexed files for a single regex pattern with metadata.

        Args:
            pattern: Regular expression to search for.
            ignore_case: If True, perform case-insensitive matching.

        Returns:
            :class:`SearchResult` with matches and metadata.
        """
        cache_key = (pattern, ignore_case)
        if cache_key in self._cache:
            return self._cache[cache_key]

        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            log_message(f"GrepEngine: invalid regex {pattern!r}: {exc}")
            return SearchResult(
                matches=[],
                meta=SearchMeta(
                    total_matches_found=0,
                    files_searched=0,
                    files_total=len(self._file_paths),
                    was_truncated=False,
                ),
            )

        result = self._search_files([compiled])
        self._cache[cache_key] = result
        return result

    def search_batch(
        self,
        patterns: list[str],
        *,
        ignore_case: bool = False,
    ) -> dict[str, list[GrepMatch]]:
        """Search all indexed files for multiple patterns in one pass.

        Each file is read once and all patterns are tested against each line.

        Args:
            patterns: List of regex patterns.
            ignore_case: If True, perform case-insensitive matching.

        Returns:
            Dict mapping each pattern string to its list of matches.
        """
        batch_result = self.search_batch_with_meta(patterns, ignore_case=ignore_case)
        return {pat: sr.matches for pat, sr in batch_result.items()}

    def search_batch_with_meta(
        self,
        patterns: list[str],
        *,
        ignore_case: bool = False,
    ) -> dict[str, SearchResult]:
        """Search all indexed files for multiple patterns with metadata.

        Each file is read once and **all** patterns are tested against each
        line, so a single line can produce matches for multiple patterns.
        This differs from :meth:`_search_files` (used by the single-pattern
        :meth:`search`), which records at most one match per line.

        Args:
            patterns: List of regex patterns.
            ignore_case: If True, perform case-insensitive matching.

        Returns:
            Dict mapping each pattern string to its :class:`SearchResult`.
        """
        flags = re.IGNORECASE if ignore_case else 0
        compiled: list[re.Pattern[str]] = []
        for p in patterns:
            try:
                compiled.append(re.compile(p, flags))
            except re.error as exc:
                log_message(f"GrepEngine: skipping invalid regex {p!r}: {exc}")
                compiled.append(re.compile(r"(?!x)x"))  # Never-matching placeholder

        # Initialize result dict
        matches: dict[str, list[GrepMatch]] = {p: [] for p in patterns}
        total_count = 0
        files_searched = 0
        was_truncated = False
        truncation_reason: str | None = None
        deadline = time.monotonic() + self._search_timeout

        for rel_path in self._file_paths:
            if total_count >= self._max_total:
                was_truncated = True
                truncation_reason = "max_total"
                break
            if time.monotonic() > deadline:
                log_message(
                    f"GrepEngine: batch search timeout ({self._search_timeout}s) reached "
                    f"after {total_count} matches"
                )
                was_truncated = True
                truncation_reason = "timeout"
                break

            abs_path = self._repo_root / str(rel_path)
            lines = self._read_file_lines(abs_path)
            if lines is None:
                continue

            files_searched += 1
            file_counts: dict[int, int] = {}  # pattern_index -> count

            for line_idx, line in enumerate(lines):
                if total_count >= self._max_total:
                    was_truncated = True
                    truncation_reason = "max_total"
                    break

                for pat_idx, regex in enumerate(compiled):
                    if file_counts.get(pat_idx, 0) >= self._max_per_file:
                        continue
                    if regex.search(line):
                        match = GrepMatch(
                            file=rel_path,
                            line_num=line_idx + 1,
                            line_content=line,
                            context_before=self._get_context(lines, line_idx, before=True),
                            context_after=self._get_context(lines, line_idx, before=False),
                        )
                        matches[patterns[pat_idx]].append(match)
                        file_counts[pat_idx] = file_counts.get(pat_idx, 0) + 1
                        total_count += 1

            # Avoid reading the next file when the limit was hit in the inner loop
            if was_truncated:
                break

        # Populate per-pattern cache so subsequent single-pattern searches hit cache.
        # Only cache when the batch was NOT truncated — truncated results may be
        # incomplete and must not pollute the single-pattern cache.
        results: dict[str, SearchResult] = {}
        for pat in patterns:
            sr = SearchResult(
                matches=matches[pat],
                meta=SearchMeta(
                    total_matches_found=len(matches[pat]),
                    files_searched=files_searched,
                    files_total=len(self._file_paths),
                    was_truncated=was_truncated,
                    truncation_reason=truncation_reason,
                ),
            )
            results[pat] = sr
            if not was_truncated:
                cache_key = (pat, ignore_case)
                if cache_key not in self._cache:
                    self._cache[cache_key] = sr

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_files(self, compiled_patterns: list[re.Pattern[str]]) -> SearchResult:
        """Search files for compiled patterns (single-pattern path).

        At most one match is recorded per line (the first matching pattern
        wins).  This differs from :meth:`search_batch_with_meta`, which
        tests every pattern against each line so that per-pattern results
        are independent.
        """
        matches: list[GrepMatch] = []
        files_searched = 0
        was_truncated = False
        truncation_reason: str | None = None
        deadline = time.monotonic() + self._search_timeout

        for rel_path in self._file_paths:
            if len(matches) >= self._max_total:
                was_truncated = True
                truncation_reason = "max_total"
                break
            if time.monotonic() > deadline:
                log_message(
                    f"GrepEngine: search timeout ({self._search_timeout}s) reached "
                    f"after {len(matches)} matches"
                )
                was_truncated = True
                truncation_reason = "timeout"
                break

            abs_path = self._repo_root / str(rel_path)
            lines = self._read_file_lines(abs_path)
            if lines is None:
                continue

            files_searched += 1
            file_match_count = 0
            for line_idx, line in enumerate(lines):
                if file_match_count >= self._max_per_file:
                    break
                if len(matches) >= self._max_total:
                    was_truncated = True
                    truncation_reason = "max_total"
                    break

                for regex in compiled_patterns:
                    if regex.search(line):
                        match = GrepMatch(
                            file=rel_path,
                            line_num=line_idx + 1,
                            line_content=line,
                            context_before=self._get_context(lines, line_idx, before=True),
                            context_after=self._get_context(lines, line_idx, before=False),
                        )
                        matches.append(match)
                        file_match_count += 1
                        break  # One match per line per search call

        return SearchResult(
            matches=matches,
            meta=SearchMeta(
                total_matches_found=len(matches),
                files_searched=files_searched,
                files_total=len(self._file_paths),
                was_truncated=was_truncated,
                truncation_reason=truncation_reason,
            ),
        )

    def _cap_line(self, line: str) -> str:
        """Truncate a line exceeding ``max_line_length`` to prevent memory issues."""
        if len(line) > self._max_line_length:
            return line[: self._max_line_length]
        return line

    def _read_file_lines(self, abs_path: Path) -> list[str] | None:
        """Read a file into lines, or return None if unreadable/binary/too large."""
        try:
            file_size = abs_path.stat().st_size
            # Check file size via stat() BEFORE reading to avoid loading
            # multi-GB files into memory just to reject them.
            if file_size > self._max_file_size:
                return None
            # Stream line-by-line for files 1-5 MB to halve peak memory
            if file_size > 1_000_000:
                return self._read_file_lines_streaming(abs_path)
            raw = abs_path.read_bytes()
            if b"\x00" in raw[:8192]:
                return None
            text = raw.decode("utf-8", errors="replace")
            if "\ufffd" in text:
                log_message(f"GrepEngine: encoding replacements in {abs_path.name}")
            return [self._cap_line(ln) for ln in text.splitlines()]
        except OSError:
            return None

    def _read_file_lines_streaming(self, abs_path: Path) -> list[str] | None:
        """Read a large file line-by-line to reduce peak memory."""
        try:
            with abs_path.open("r", encoding="utf-8", errors="replace") as f:
                # Check for binary content in first chunk.
                # NUL bytes survive UTF-8 decoding (U+0000 is valid), so
                # checking the decoded str for "\x00" is equivalent to the
                # bytes-level b"\x00" check in the non-streaming path.
                first_chunk = f.read(8192)
                if "\x00" in first_chunk:
                    return None
                has_replacement = "\ufffd" in first_chunk
                # The chunk may end mid-line.  Keep the trailing partial
                # (a fragment without a terminating newline) and prepend it
                # to the first line the iterator yields so no line is split.
                chunk_lines = first_chunk.splitlines(True)
                if chunk_lines and not chunk_lines[-1].endswith(("\n", "\r")):
                    leftover = chunk_lines.pop()
                else:
                    leftover = ""
                lines: list[str] = list(chunk_lines)
                first_from_iter = True
                for line in f:
                    if not has_replacement and "\ufffd" in line:
                        has_replacement = True
                    if first_from_iter and leftover:
                        line = leftover + line
                        first_from_iter = False
                    lines.append(line)
                # If the file ended exactly at the chunk boundary, flush leftover.
                if first_from_iter and leftover:
                    lines.append(leftover)
            if has_replacement:
                log_message(f"GrepEngine: encoding replacements in {abs_path.name}")
            return [self._cap_line(line.rstrip("\r\n")) for line in lines]
        except OSError:
            return None

    def _get_context(self, lines: list[str], line_idx: int, *, before: bool) -> tuple[str, ...]:
        """Extract context lines before or after a match."""
        if self._context_lines <= 0:
            return ()
        if before:
            start = max(0, line_idx - self._context_lines)
            return tuple(lines[start:line_idx])
        else:
            end = min(len(lines), line_idx + 1 + self._context_lines)
            return tuple(lines[line_idx + 1 : end])


__all__ = ["GrepEngine", "GrepMatch", "SearchMeta", "SearchResult"]
