"""Fast file indexing with fuzzy search for INGOT codebase discovery.

Walks the repository using ``git ls-files`` (respecting .gitignore),
indexes files by stem and extension, and provides fuzzy lookup so that
tools like PlanFixer can auto-correct mistyped paths.

Session-scoped: instantiate once per plan generation run.
"""

from __future__ import annotations

import functools
import subprocess
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from ingot.utils.logging import log_message


class FileIndex:
    """Index of repository files for fast lookup by stem, extension, or glob.

    Built from ``git ls-files`` output so .gitignore is respected
    without re-implementing exclusion logic.

    Args:
        repo_root: Absolute path to the repository root.
        max_files: Safety cap on files to index (default 100_000).
    """

    def __init__(self, repo_root: Path, *, max_files: int = 100_000) -> None:
        self._repo_root = repo_root.resolve()
        self._max_files = max_files

        # stem (lower) -> list of relative PurePosixPath
        self._by_stem: dict[str, list[PurePosixPath]] = defaultdict(list)
        # extension (lower, without dot) -> list of relative PurePosixPath
        self._by_ext: dict[str, list[PurePosixPath]] = defaultdict(list)
        # All indexed paths (relative PurePosixPath)
        self._all_paths: list[PurePosixPath] = []
        # Glob result cache (session-scoped)
        self._glob_cache: dict[str, list[PurePosixPath]] = {}

        self._build_index()

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build_index(self) -> None:
        """Populate the index from ``git ls-files``."""
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=self._repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            log_message(f"FileIndex: git ls-files failed: {exc}")
            return

        if result.returncode != 0:
            log_message(f"FileIndex: git ls-files exited {result.returncode}")
            return

        entries = result.stdout.split("\0")
        count = 0
        for entry in entries:
            if not entry:
                continue
            if count >= self._max_files:
                log_message(f"FileIndex: hit max_files cap ({self._max_files}), stopping indexing")
                break

            path = PurePosixPath(entry)
            self._all_paths.append(path)

            stem = path.stem.lower()
            self._by_stem[stem].append(path)

            ext = path.suffix.lstrip(".").lower()
            if ext:
                self._by_ext[ext].append(path)

            count += 1

        log_message(f"FileIndex: indexed {count} files from {self._repo_root}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def repo_root(self) -> Path:
        """The repository root this index was built from."""
        return self._repo_root

    @property
    def file_count(self) -> int:
        """Number of indexed files."""
        return len(self._all_paths)

    def find_by_stem(self, stem: str) -> list[PurePosixPath]:
        """Find all files whose stem matches (case-insensitive).

        Args:
            stem: File stem to search for (e.g. ``"FooTest"``).

        Returns:
            List of relative paths matching the stem.
        """
        return list(self._by_stem.get(stem.lower(), []))

    def find_by_extension(self, ext: str) -> list[PurePosixPath]:
        """Find all files with the given extension (case-insensitive).

        Args:
            ext: Extension without dot (e.g. ``"java"``, ``"py"``).

        Returns:
            List of relative paths with that extension.
        """
        return list(self._by_ext.get(ext.lower().lstrip("."), []))

    def find_by_glob(self, pattern: str) -> list[PurePosixPath]:
        """Find files matching a glob pattern.

        Results are cached by pattern for the lifetime of this index.

        Args:
            pattern: Glob pattern (e.g. ``"src/**/*.java"``).

        Returns:
            List of matching relative paths.
        """
        if pattern in self._glob_cache:
            return list(self._glob_cache[pattern])
        result = [p for p in self._all_paths if fnmatch(str(p), pattern)]
        self._glob_cache[pattern] = result
        return list(result)

    def fuzzy_find(self, filename: str) -> PurePosixPath | None:
        """Find a file by fuzzy matching — stem + extension, then stem only.

        Returns the path only if there is a *unique* match.
        Ambiguous matches (multiple candidates) return ``None``.

        Args:
            filename: Filename to search for (e.g. ``"FooTest.java"``).

        Returns:
            Unique matching path, or ``None``.
        """
        pure = PurePosixPath(filename)
        target_stem = pure.stem.lower()
        target_ext = pure.suffix.lstrip(".").lower()

        # Strategy 1: stem + extension match
        if target_ext:
            candidates = [
                p
                for p in self._by_stem.get(target_stem, [])
                if p.suffix.lstrip(".").lower() == target_ext
            ]
            if len(candidates) == 1:
                return candidates[0]

        # Strategy 2: stem-only match (if extension didn't yield unique result)
        stem_matches = self._by_stem.get(target_stem, [])
        if len(stem_matches) == 1:
            return stem_matches[0]

        return None

    def exists(self, rel_path: str) -> bool:
        """Check if a relative path exists in the index.

        Args:
            rel_path: Relative path from repo root (e.g. ``"src/main/Foo.java"``).
        """
        target = PurePosixPath(rel_path)
        return target in self._all_paths_set

    @functools.cached_property
    def _all_paths_set(self) -> frozenset[PurePosixPath]:
        """Lazy-built set for O(1) existence checks."""
        return frozenset(self._all_paths)

    def all_paths(self) -> list[PurePosixPath]:
        """Return all indexed paths (relative to repo root)."""
        return list(self._all_paths)


__all__ = ["FileIndex"]
