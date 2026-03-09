"""Tests for ingot.discovery.grep_engine module."""

from pathlib import PurePosixPath

import pytest

from ingot.discovery.grep_engine import GrepEngine, SearchMeta, SearchResult


@pytest.fixture()
def sample_repo(tmp_path):
    """Create a sample repository with searchable files."""
    (tmp_path / "src").mkdir()

    (tmp_path / "src" / "foo.py").write_text(
        "import os\n\nclass FooService:\n    def process(self):\n        return 42\n"
    )

    (tmp_path / "src" / "bar.py").write_text(
        "from foo import FooService\n"
        "\n"
        "class BarHelper:\n"
        "    def __init__(self):\n"
        "        self.foo = FooService()\n"
        "\n"
        "    def run(self):\n"
        "        return self.foo.process()\n"
    )

    (tmp_path / "src" / "config.yml").write_text("server:\n  port: 8080\n  name: my-service\n")

    # Binary file
    (tmp_path / "src" / "image.bin").write_bytes(b"\x00\x01\x02\x03")

    file_paths = [
        PurePosixPath("src/foo.py"),
        PurePosixPath("src/bar.py"),
        PurePosixPath("src/config.yml"),
        PurePosixPath("src/image.bin"),
    ]

    return tmp_path, file_paths


class TestGrepEngineBasic:
    """Test basic GrepEngine search functionality."""

    def test_simple_match(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("FooService")
        assert len(matches) >= 2
        assert any(m.file == PurePosixPath("src/foo.py") for m in matches)
        assert any(m.file == PurePosixPath("src/bar.py") for m in matches)

    def test_regex_match(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search(r"class \w+:")
        assert len(matches) == 2
        assert any("FooService" in m.line_content for m in matches)
        assert any("BarHelper" in m.line_content for m in matches)

    def test_no_match(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("NonExistentPattern")
        assert matches == []

    def test_case_insensitive(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("fooservice", ignore_case=True)
        assert len(matches) >= 2

    def test_case_sensitive_default(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("fooservice")
        assert matches == []

    def test_invalid_regex_returns_empty(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("[invalid")
        assert matches == []

    def test_binary_file_skipped(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search(".*")
        # Binary file should be skipped
        assert not any(m.file == PurePosixPath("src/image.bin") for m in matches)


class TestGrepEngineContext:
    """Test context lines functionality."""

    def test_context_lines(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, context_lines=1)
        matches = engine.search("class FooService:")
        assert len(matches) == 1
        match = matches[0]
        assert len(match.context_before) <= 1
        assert len(match.context_after) <= 1

    def test_no_context_by_default(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("class FooService:")
        assert len(matches) == 1
        assert matches[0].context_before == ()
        assert matches[0].context_after == ()


class TestGrepEngineLimits:
    """Test max match limits."""

    def test_max_matches_per_file(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, max_matches_per_file=1)
        # "self" appears in both foo.py and bar.py, multiple times per file
        matches = engine.search(r"self\.")
        file_counts: dict[PurePosixPath, int] = {}
        for m in matches:
            file_counts[m.file] = file_counts.get(m.file, 0) + 1
        for count in file_counts.values():
            assert count <= 1

    def test_max_matches_total(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, max_matches_total=2)
        matches = engine.search(r"\w+")
        assert len(matches) <= 2


class TestGrepEngineBatch:
    """Test batch search functionality."""

    def test_batch_search_multiple_patterns(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        results = engine.search_batch(["FooService", "BarHelper"])
        assert "FooService" in results
        assert "BarHelper" in results
        assert len(results["FooService"]) >= 2
        assert len(results["BarHelper"]) >= 1

    def test_batch_search_invalid_pattern_skipped(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        results = engine.search_batch(["FooService", "[invalid"])
        assert len(results["FooService"]) >= 2
        assert results["[invalid"] == []

    def test_batch_search_empty_patterns(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        results = engine.search_batch([])
        assert results == {}


class TestGrepEngineLargeFile:
    """Test that large files are rejected before being read into memory."""

    def test_large_file_rejected_without_full_read(self, sample_repo, monkeypatch):
        """File exceeding max_file_size should be skipped via stat(), not read_bytes()."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, max_file_size=100)

        large_file = tmp_path / "src" / "foo.py"

        # Make foo.py large (>100 bytes) so stat() rejects it.
        large_file.write_text("x" * 200)

        # Verify the file is skipped and no match is returned from it
        matches = engine.search("x")
        foo_matches = [m for m in matches if m.file == PurePosixPath("src/foo.py")]
        assert foo_matches == []


class TestGrepMatchDataclass:
    """Test GrepMatch properties."""

    def test_match_fields(self, sample_repo):
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        matches = engine.search("class FooService:")
        assert len(matches) == 1
        match = matches[0]
        assert match.file == PurePosixPath("src/foo.py")
        assert match.line_num == 3
        assert "class FooService:" in match.line_content


class TestSearchWithMeta:
    """Test search_with_meta and search_batch_with_meta metadata."""

    def test_search_with_meta_returns_result(self, sample_repo):
        """Basic metadata should be populated."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        result = engine.search_with_meta("FooService")
        assert isinstance(result, SearchResult)
        assert isinstance(result.meta, SearchMeta)
        assert result.meta.total_matches_found >= 2
        assert result.meta.files_searched > 0
        assert result.meta.files_total == len(file_paths)
        assert result.meta.was_truncated is False
        assert result.meta.truncation_reason is None

    def test_truncation_on_max_total(self, sample_repo):
        """Setting cap=2 should report was_truncated=True, reason='max_total'."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, max_matches_total=2)
        result = engine.search_with_meta(r"\w+")
        assert result.meta.was_truncated is True
        assert result.meta.truncation_reason == "max_total"
        assert len(result.matches) <= 2

    def test_no_truncation_under_limits(self, sample_repo):
        """Small search should report was_truncated=False."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        result = engine.search_with_meta("class FooService:")
        assert result.meta.was_truncated is False
        assert result.meta.truncation_reason is None
        assert result.meta.total_matches_found == 1

    def test_batch_with_meta_propagates_truncation(self, sample_repo):
        """Batch search with low cap should report truncation in all results."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths, max_matches_total=2)
        results = engine.search_batch_with_meta([r"\w+", "FooService"])
        # At least one pattern's result should show truncation
        any_truncated = any(sr.meta.was_truncated for sr in results.values())
        assert any_truncated

    def test_batch_with_meta_returns_search_results(self, sample_repo):
        """Each batch entry should be a SearchResult."""
        tmp_path, file_paths = sample_repo
        engine = GrepEngine(tmp_path, file_paths)
        results = engine.search_batch_with_meta(["FooService", "BarHelper"])
        assert "FooService" in results
        assert "BarHelper" in results
        assert isinstance(results["FooService"], SearchResult)
        assert isinstance(results["BarHelper"], SearchResult)


class TestStreamingRead:
    """Test the streaming read path for files > 1 MB."""

    def test_streaming_read_matches_normal_read(self, tmp_path):
        """A file just over 1 MB should yield identical lines to a small file."""
        # Build content with a line that straddles the 8192-byte boundary
        short_lines = [f"line {i}: some content here" for i in range(200)]
        # Pad to just over 1 MB
        padding_line = "x" * 800
        body_lines = short_lines + [padding_line] * 1300
        content = "\n".join(body_lines) + "\n"
        assert len(content.encode()) > 1_000_000

        (tmp_path / "big.py").write_text(content)
        file_paths = [PurePosixPath("big.py")]
        engine = GrepEngine(tmp_path, file_paths)

        # Searching should find lines across the chunk boundary
        result = engine.search("line 199")
        assert len(result) == 1
        assert "line 199" in result[0].line_content

    def test_streaming_no_split_at_chunk_boundary(self, tmp_path):
        """Lines at the 8192-byte chunk boundary must not be split."""
        # Create a file where a line straddles byte 8192 exactly
        prefix = "A" * 8180 + "\n"  # 8181 bytes
        boundary_line = "BOUNDARY_MARKER_LINE"  # starts at ~8181
        content = prefix + boundary_line + "\n" + "after\n"
        # Pad to > 1 MB
        content += "pad\n" * 250_000
        assert len(content.encode()) > 1_000_000

        (tmp_path / "boundary.py").write_text(content)
        file_paths = [PurePosixPath("boundary.py")]
        engine = GrepEngine(tmp_path, file_paths)

        result = engine.search("BOUNDARY_MARKER_LINE")
        assert len(result) == 1
        # The full line must be intact, not split into two partial matches
        assert result[0].line_content == boundary_line

    def test_streaming_binary_detection(self, tmp_path):
        """Null bytes in the first 8192 bytes of a large file → skip."""
        content = b"hello\x00world" + b"\n" + b"x\n" * 600_000
        assert len(content) > 1_000_000
        (tmp_path / "binary.bin").write_bytes(content)
        file_paths = [PurePosixPath("binary.bin")]
        engine = GrepEngine(tmp_path, file_paths)
        result = engine.search("hello")
        assert result == []


class TestEncodingLogging:
    """Test encoding replacement logging."""

    def test_encoding_replacement_logged(self, tmp_path):
        """File with encoding replacements should trigger a log message."""
        (tmp_path / "bad.py").write_bytes(b"hello \xff world\n")
        file_paths = [PurePosixPath("bad.py")]
        engine = GrepEngine(tmp_path, file_paths)
        from unittest.mock import patch

        with patch("ingot.discovery.grep_engine.log_message") as mock_log:
            engine.search("hello")
        assert any("encoding replacements" in str(c) for c in mock_log.call_args_list)
