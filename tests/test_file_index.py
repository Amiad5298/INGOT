"""Tests for ingot.discovery.file_index module."""

from pathlib import PurePosixPath
from unittest.mock import patch

import pytest

from ingot.discovery.file_index import FileIndex


@pytest.fixture()
def sample_repo(tmp_path):
    """Create a sample repository structure for testing."""
    # Create some files
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "src" / "test" / "java").mkdir(parents=True)
    (tmp_path / "config").mkdir()

    files = [
        "src/main/java/FooService.java",
        "src/main/java/BarHelper.java",
        "src/main/java/BazController.java",
        "src/test/java/FooServiceTest.java",
        "src/test/java/BarHelperTest.java",
        "config/application.yml",
        "config/application-dev.yml",
        "README.md",
        "pom.xml",
    ]
    for f in files:
        (tmp_path / f).touch()

    return tmp_path, files


def _make_file_index(tmp_path, files):
    """Build a FileIndex by mocking git ls-files."""
    git_output = "\0".join(files) + "\0"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": git_output,
            },
        )()
        return FileIndex(tmp_path)


class TestFileIndexBuilding:
    """Test FileIndex construction."""

    def test_index_counts_all_files(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        assert idx.file_count == len(files)

    def test_index_empty_on_git_failure(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type(
                "Result",
                (),
                {
                    "returncode": 128,
                    "stdout": "",
                },
            )()
            idx = FileIndex(tmp_path)
        assert idx.file_count == 0

    def test_index_respects_max_files(self, sample_repo):
        tmp_path, files = sample_repo
        git_output = "\0".join(files) + "\0"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": git_output,
                },
            )()
            idx = FileIndex(tmp_path, max_files=3)
        assert idx.file_count == 3

    def test_repo_root_property(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        assert idx.repo_root == tmp_path.resolve()


class TestFileIndexSearch:
    """Test FileIndex search methods."""

    def test_find_by_stem_case_insensitive(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_stem("fooservice")
        assert len(results) == 1
        assert results[0] == PurePosixPath("src/main/java/FooService.java")

    def test_find_by_stem_multiple_matches(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        # "application" matches both application.yml and application-dev.yml
        results = idx.find_by_stem("application")
        assert len(results) == 1  # Only exact stem match

    def test_find_by_stem_no_match(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_stem("NonExistent")
        assert results == []

    def test_find_by_extension(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_extension("java")
        assert len(results) == 5

    def test_find_by_extension_case_insensitive(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_extension("JAVA")
        assert len(results) == 5

    def test_find_by_extension_with_dot(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_extension(".yml")
        assert len(results) == 2

    def test_find_by_glob(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_glob("src/test/**/*.java")
        assert len(results) == 2

    def test_find_by_glob_no_match(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        results = idx.find_by_glob("*.py")
        assert results == []


class TestFileIndexFuzzyFind:
    """Test FileIndex fuzzy_find method."""

    def test_fuzzy_find_unique_stem_and_ext(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        result = idx.fuzzy_find("FooService.java")
        assert result == PurePosixPath("src/main/java/FooService.java")

    def test_fuzzy_find_unique_stem_only(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        result = idx.fuzzy_find("README.txt")  # Wrong ext but unique stem
        assert result == PurePosixPath("README.md")

    def test_fuzzy_find_ambiguous_returns_none(self, tmp_path):
        """Multiple files with same stem → None."""
        files = ["src/Foo.java", "test/Foo.java"]
        idx = _make_file_index(tmp_path, files)
        result = idx.fuzzy_find("Foo.java")
        assert result is None

    def test_fuzzy_find_no_match_returns_none(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        result = idx.fuzzy_find("NonExistent.java")
        assert result is None

    def test_fuzzy_find_test_file(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        result = idx.fuzzy_find("FooServiceTest.java")
        assert result == PurePosixPath("src/test/java/FooServiceTest.java")


class TestFileIndexExists:
    """Test FileIndex existence check."""

    def test_exists_returns_true_for_indexed_path(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        assert idx.exists("src/main/java/FooService.java") is True

    def test_exists_returns_false_for_missing_path(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        assert idx.exists("src/main/java/Missing.java") is False

    def test_all_paths_returns_all_indexed(self, sample_repo):
        tmp_path, files = sample_repo
        idx = _make_file_index(tmp_path, files)
        all_paths = idx.all_paths()
        assert len(all_paths) == len(files)
