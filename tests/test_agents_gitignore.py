"""Tests for SPECFLOW gitignore management in agents.py.

Tests the ensure_gitignore_configured() function and related utilities
that manage the target project's .gitignore file.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from specflow.integrations.agents import (
    _check_gitignore_has_pattern,
    ensure_gitignore_configured,
    SPECFLOW_GITIGNORE_PATTERNS,
    SPECFLOW_GITIGNORE_MARKER,
)


class TestCheckGitignoreHasPattern:
    """Tests for _check_gitignore_has_pattern helper function."""

    def test_finds_exact_pattern_match(self):
        """Returns True when pattern exists exactly."""
        content = "*.pyc\n.specflow/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".specflow/") is True

    def test_finds_pattern_with_surrounding_whitespace(self):
        """Returns True when pattern has leading/trailing whitespace."""
        content = "*.pyc\n  .specflow/  \n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".specflow/") is True

    def test_does_not_match_partial_pattern(self):
        """Returns False when pattern is substring of another."""
        content = "*.pyc\n.specflow-backup/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".specflow/") is False

    def test_does_not_match_commented_pattern(self):
        """Returns False when pattern is in a comment."""
        content = "*.pyc\n# .specflow/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".specflow/") is False

    def test_finds_log_pattern(self):
        """Returns True for *.log pattern."""
        content = "*.pyc\n*.log\n__pycache__/"
        assert _check_gitignore_has_pattern(content, "*.log") is True

    def test_returns_false_for_missing_pattern(self):
        """Returns False when pattern is not in file."""
        content = "*.pyc\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".specflow/") is False

    def test_handles_empty_content(self):
        """Returns False for empty content."""
        assert _check_gitignore_has_pattern("", ".specflow/") is False

    def test_handles_only_comments(self):
        """Returns False when file has only comments."""
        content = "# Python\n# Ignore pyc files"
        assert _check_gitignore_has_pattern(content, ".specflow/") is False


class TestEnsureGitignoreConfigured:
    """Tests for ensure_gitignore_configured function."""

    def test_creates_gitignore_if_not_exists(self, tmp_path, monkeypatch):
        """Creates .gitignore with SPECFLOW patterns if file doesn't exist."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # File should not exist initially
        assert not gitignore_path.exists()

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        assert gitignore_path.exists()

        content = gitignore_path.read_text()
        assert SPECFLOW_GITIGNORE_MARKER in content
        for pattern in SPECFLOW_GITIGNORE_PATTERNS:
            assert pattern in content

    def test_appends_to_existing_gitignore(self, tmp_path, monkeypatch):
        """Appends SPECFLOW patterns to existing .gitignore."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create existing .gitignore with some content
        existing_content = "# Python\n*.pyc\n__pycache__/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Original content should be preserved
        assert "# Python" in content
        assert "*.pyc" in content
        assert "__pycache__/" in content

        # SPECFLOW patterns should be added
        assert SPECFLOW_GITIGNORE_MARKER in content
        for pattern in SPECFLOW_GITIGNORE_PATTERNS:
            assert pattern in content

    def test_idempotent_does_not_duplicate(self, tmp_path, monkeypatch):
        """Running multiple times does not duplicate patterns."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Run twice
        ensure_gitignore_configured(quiet=True)
        first_content = gitignore_path.read_text()

        ensure_gitignore_configured(quiet=True)
        second_content = gitignore_path.read_text()

        # Content should be identical
        assert first_content == second_content

        # Each pattern should appear exactly once
        for pattern in SPECFLOW_GITIGNORE_PATTERNS:
            assert second_content.count(pattern) == 1

    def test_preserves_existing_content_exactly(self, tmp_path, monkeypatch):
        """Existing content is preserved without modification."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create existing .gitignore with specific formatting
        existing_content = """# My Project
*.pyc
__pycache__/

# IDE
.idea/
.vscode/
"""
        gitignore_path.write_text(existing_content)

        ensure_gitignore_configured(quiet=True)
        content = gitignore_path.read_text()

        # Original content should appear at the start unchanged
        assert content.startswith(existing_content.rstrip())

    def test_skips_if_patterns_already_exist(self, tmp_path, monkeypatch):
        """Does nothing if all patterns already exist."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with SPECFLOW patterns already present
        existing_content = "*.pyc\n.specflow/\n*.log\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Content should be unchanged
        assert content == existing_content

    def test_adds_only_missing_patterns(self, tmp_path, monkeypatch):
        """Only adds patterns that are missing."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with only one SPECFLOW pattern
        existing_content = "*.pyc\n.specflow/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # .specflow/ should appear only once (not duplicated)
        assert content.count(".specflow/") == 1
        # *.log should be added
        assert "*.log" in content

    def test_handles_file_without_trailing_newline(self, tmp_path, monkeypatch):
        """Handles existing file that doesn't end with newline."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore without trailing newline
        existing_content = "*.pyc\n__pycache__"  # No trailing newline
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Should have proper separation (patterns not on same line as existing)
        lines = content.split("\n")
        assert "__pycache__" in lines or "__pycache__" == lines[1].strip()

        # All patterns should be on their own lines
        for pattern in SPECFLOW_GITIGNORE_PATTERNS:
            assert pattern in lines or any(line.strip() == pattern for line in lines)

    def test_adds_marker_comment_only_once(self, tmp_path, monkeypatch):
        """SPECFLOW marker comment is added only once."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with marker but only one pattern
        existing_content = f"*.pyc\n{SPECFLOW_GITIGNORE_MARKER}\n.specflow/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Marker should appear only once
        assert content.count(SPECFLOW_GITIGNORE_MARKER) == 1
        # Missing pattern should be added
        assert "*.log" in content

    def test_returns_true_when_already_configured(self, tmp_path, monkeypatch):
        """Returns True when .gitignore is already properly configured."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create fully configured .gitignore
        gitignore_path.write_text(".specflow/\n*.log\n")

        result = ensure_gitignore_configured(quiet=True)
        assert result is True

    @patch("specflow.integrations.agents.print_info")
    def test_prints_info_when_not_quiet(self, mock_print, tmp_path, monkeypatch):
        """Prints info message when quiet=False and patterns are added."""
        monkeypatch.chdir(tmp_path)

        ensure_gitignore_configured(quiet=False)

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert ".gitignore" in call_args
        assert "SPECFLOW" in call_args

    def test_does_not_modify_patterns_in_comments(self, tmp_path, monkeypatch):
        """Patterns in comments are not considered as existing."""
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with patterns only in comments
        existing_content = "# Ignore .specflow/ for logs\n# *.log files\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Both patterns should be added as actual rules (not just comments)
        lines = [l.strip() for l in content.split("\n") if not l.strip().startswith("#")]
        assert ".specflow/" in lines
        assert "*.log" in lines

