"""Convention-based source-to-test file mapping for INGOT codebase discovery.

Maps source files to their test counterparts using language-specific
naming conventions. Uses :class:`FileIndex` for fast lookups across
test directories.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ingot.discovery.file_index import FileIndex

# Language-specific test file name generators.
# Each entry: (extension, list of stem transformers)
# A stem transformer takes a source file stem and returns candidate test stems.
_TEST_CONVENTIONS: dict[str, list[str]] = {
    # Java: FooService.java → FooServiceTest.java, FooServiceTests.java, FooServiceSpec.java
    ".java": ["{stem}Test", "{stem}Tests", "{stem}Spec", "{stem}IT"],
    # Kotlin: same as Java
    ".kt": ["{stem}Test", "{stem}Tests", "{stem}Spec"],
    # Python: foo.py → test_foo.py, foo_test.py
    ".py": ["test_{stem}", "{stem}_test"],
    # TypeScript/JavaScript: foo.ts → foo.spec.ts, foo.test.ts
    ".ts": ["{stem}.spec", "{stem}.test"],
    ".tsx": ["{stem}.spec", "{stem}.test"],
    ".js": ["{stem}.spec", "{stem}.test"],
    ".jsx": ["{stem}.spec", "{stem}.test"],
    # Go: foo.go → foo_test.go (same directory by convention)
    ".go": ["{stem}_test"],
    # Ruby: foo.rb → foo_spec.rb, foo_test.rb, test_foo.rb
    ".rb": ["{stem}_spec", "{stem}_test", "test_{stem}"],
    # Rust: foo.rs → foo_test.rs (or inline #[cfg(test)])
    ".rs": ["{stem}_test"],
    # C#: Foo.cs → FooTests.cs, FooTest.cs
    ".cs": ["{stem}Tests", "{stem}Test"],
    # Swift: Foo.swift → FooTests.swift
    ".swift": ["{stem}Tests", "{stem}Test"],
}


class TestMapper:
    """Map source files to test files using naming conventions.

    Args:
        file_index: FileIndex for fast lookups.
    """

    def __init__(self, file_index: FileIndex) -> None:
        self._file_index = file_index

    def find_tests(self, source_path: str | PurePosixPath) -> list[PurePosixPath]:
        """Find test files for a given source file.

        Args:
            source_path: Relative path of the source file.

        Returns:
            List of test file paths (may be empty).
        """
        path = PurePosixPath(source_path)
        stem = path.stem
        suffix = path.suffix.lower()

        conventions = _TEST_CONVENTIONS.get(suffix)
        if not conventions:
            return []

        results: list[PurePosixPath] = []
        seen: set[PurePosixPath] = set()

        for template in conventions:
            test_stem = template.format(stem=stem)
            candidates = self._file_index.find_by_stem(test_stem)
            for candidate in candidates:
                # Must have same extension (or .ts variants for .tsx, etc.)
                if self._compatible_extension(suffix, candidate.suffix.lower()):
                    if candidate not in seen:
                        seen.add(candidate)
                        results.append(candidate)

        # Prefer test files in recognised test directories, with proximity awareness.
        results.sort(key=lambda c: self._score_test_path(c, path))
        return results

    _TEST_DIR_NAMES: frozenset[str] = frozenset({"test", "tests", "__tests__", "spec", "specs"})

    _STRIP_PREFIXES: frozenset[str] = frozenset(
        {
            "src",
            "lib",
            "app",
            "test",
            "tests",
            "__tests__",
            "spec",
            "specs",
        }
    )

    @staticmethod
    def _extract_package_path(path: PurePosixPath) -> tuple[str, ...]:
        """Strip common source/test prefixes, return package components."""
        parts = list(path.parts[:-1])  # exclude filename
        # Strip leading src/{main,test}/{java,kotlin,scala}
        if len(parts) >= 3 and parts[0] == "src" and parts[1] in ("main", "test"):
            if parts[2] in ("java", "kotlin", "scala"):
                parts = parts[3:]
            else:
                parts = parts[2:]
        # Strip single common prefix dirs (src/, lib/, tests/, etc.)
        elif parts and parts[0].lower() in TestMapper._STRIP_PREFIXES:
            parts = parts[1:]
        return tuple(parts)

    @staticmethod
    def _score_test_path(test_path: PurePosixPath, source_path: PurePosixPath) -> tuple[int, int]:
        """Score a test path relative to a source path.

        Returns ``(tier, -shared_components)`` — lower is better.

        Tier 0: Same parent dir (Go convention)
        Tier 1: Mirror structure under recognized test dir
        Tier 2: Any recognized test directory
        Tier 3: Everything else
        """
        test_parts = {p.lower() for p in test_path.parts}
        has_test_dir = bool(test_parts & TestMapper._TEST_DIR_NAMES)

        # Shared prefix component count for tie-breaking
        src_pkg = TestMapper._extract_package_path(source_path)
        test_pkg = TestMapper._extract_package_path(test_path)
        shared = 0
        for s, t in zip(src_pkg, test_pkg, strict=False):
            if s == t:
                shared += 1
            else:
                break

        # Tier 0: same parent directory
        if test_path.parent == source_path.parent:
            return (0, -shared)

        # Tier 1: recognized test dir AND package path mirrors source.
        # Both must be non-empty — flat projects with no package structure
        # (empty tuples) fall through to tier 2 since there is nothing to mirror.
        if has_test_dir and src_pkg and test_pkg and src_pkg == test_pkg:
            return (1, -shared)

        # Tier 2: any recognized test directory
        if has_test_dir:
            return (2, -shared)

        # Tier 3: fallback
        return (3, -shared)

    def map_all(self, source_paths: list[str | PurePosixPath]) -> dict[str, list[PurePosixPath]]:
        """Map multiple source files to their tests.

        Args:
            source_paths: List of source file relative paths.

        Returns:
            Dict mapping source path string → list of test paths.
        """
        result: dict[str, list[PurePosixPath]] = {}
        for src in source_paths:
            tests = self.find_tests(src)
            if tests:
                result[str(src)] = tests
        return result

    @staticmethod
    def _compatible_extension(source_ext: str, test_ext: str) -> bool:
        """Check if a test file extension is compatible with the source."""
        if source_ext == test_ext:
            return True
        # TypeScript variants
        ts_group = {".ts", ".tsx"}
        if source_ext in ts_group and test_ext in ts_group:
            return True
        # JavaScript variants
        js_group = {".js", ".jsx"}
        if source_ext in js_group and test_ext in js_group:
            return True
        return False


__all__ = ["TestMapper"]
