"""Tests for SPECFLOW gitignore management in agents.py.

Tests the ensure_gitignore_configured() function and related utilities
that manage the target project's .gitignore file.
"""

from unittest.mock import patch

from spec.integrations.agents import (
    SPECFLOW_GITIGNORE_MARKER,
    SPECFLOW_GITIGNORE_PATTERNS,
    _check_gitignore_has_pattern,
    ensure_gitignore_configured,
)


class TestCheckGitignoreHasPattern:
    """Tests for _check_gitignore_has_pattern helper function."""

    def test_finds_exact_pattern_match(self):
        """Returns True when pattern exists exactly."""
        content = "*.pyc\n.spec/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".spec/") is True

    def test_finds_pattern_with_surrounding_whitespace(self):
        """Returns True when pattern has leading/trailing whitespace."""
        content = "*.pyc\n  .spec/  \n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".spec/") is True

    def test_does_not_match_partial_pattern(self):
        """Returns False when pattern is substring of another."""
        content = "*.pyc\n.specflow-backup/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".spec/") is False

    def test_does_not_match_commented_pattern(self):
        """Returns False when pattern is in a comment."""
        content = "*.pyc\n# .spec/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".spec/") is False

    def test_finds_log_pattern(self):
        """Returns True for *.log pattern."""
        content = "*.pyc\n*.log\n__pycache__/"
        assert _check_gitignore_has_pattern(content, "*.log") is True

    def test_returns_false_for_missing_pattern(self):
        """Returns False when pattern is not in file."""
        content = "*.pyc\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".spec/") is False

    def test_handles_empty_content(self):
        """Returns False for empty content."""
        assert _check_gitignore_has_pattern("", ".spec/") is False

    def test_handles_only_comments(self):
        """Returns False when file has only comments."""
        content = "# Python\n# Ignore pyc files"
        assert _check_gitignore_has_pattern(content, ".spec/") is False


class TestGitignorePatternsConfiguration:
    """Tests for SPECFLOW_GITIGNORE_PATTERNS configuration.

    These tests verify the patterns list is correctly configured to:
    - Ignore runtime artifacts (.spec/, *.log)
    - NOT ignore user-visible files (specs/ directory with plan/tasklist .md files)
    """

    def test_patterns_include_spec_directory(self):
        """The .spec/ directory should be ignored (runtime state/logs)."""
        assert ".spec/" in SPECFLOW_GITIGNORE_PATTERNS

    def test_patterns_include_log_files(self):
        """Log files (*.log) should be ignored."""
        assert "*.log" in SPECFLOW_GITIGNORE_PATTERNS

    def test_patterns_do_not_include_specs_directory(self):
        """REGRESSION TEST: specs/ must NOT be ignored.

        The specs/ directory contains plan and tasklist .md files that users
        need to see and review. Previously, specs/ was incorrectly added to
        gitignore patterns, causing users to not see their plan files.
        """
        assert "specs/" not in SPECFLOW_GITIGNORE_PATTERNS
        assert "specs" not in SPECFLOW_GITIGNORE_PATTERNS

    def test_patterns_only_contain_expected_entries(self):
        """Verify the exact patterns list to catch unexpected additions."""
        expected_patterns = [".spec/", "*.log"]
        assert SPECFLOW_GITIGNORE_PATTERNS == expected_patterns


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
        existing_content = "*.pyc\n.spec/\n*.log\n"
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
        existing_content = "*.pyc\n.spec/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # .spec/ should appear only once (not duplicated)
        assert content.count(".spec/") == 1
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
        existing_content = f"*.pyc\n{SPECFLOW_GITIGNORE_MARKER}\n.spec/\n"
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
        gitignore_path.write_text(".spec/\n*.log\n")

        result = ensure_gitignore_configured(quiet=True)
        assert result is True

    @patch("spec.integrations.agents.print_info")
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
        existing_content = "# Ignore .spec/ for logs\n# *.log files\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # All patterns should be added as actual rules (not just comments)
        lines = [line.strip() for line in content.split("\n") if not line.strip().startswith("#")]
        assert ".spec/" in lines
        assert "*.log" in lines


class TestRepoRootDetection:
    """Tests for git repository root detection in gitignore configuration."""

    def test_updates_gitignore_at_repo_root_from_subdir(self, tmp_path, monkeypatch):
        """When running from a subdirectory, .gitignore is updated at repo root."""
        # Create a git repo structure
        repo_root = tmp_path / "my-repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        (repo_root / ".gitignore").write_text("node_modules/\n")

        # Create nested subdirectory
        subdir = repo_root / "src" / "deep" / "nested"
        subdir.mkdir(parents=True)

        # Change to nested directory
        monkeypatch.chdir(subdir)

        # Run the function
        result = ensure_gitignore_configured(quiet=True)

        assert result is True

        # .gitignore at repo root should be updated
        content = (repo_root / ".gitignore").read_text()
        assert ".spec/" in content
        assert "*.log" in content

        # No .gitignore should be created in the subdirectory
        assert not (subdir / ".gitignore").exists()

    def test_falls_back_to_cwd_when_not_in_git_repo(self, tmp_path, monkeypatch):
        """When not in a git repo, .gitignore is created in current directory."""
        # Create a directory without .git
        no_git_dir = tmp_path / "no-git-project"
        no_git_dir.mkdir()
        monkeypatch.chdir(no_git_dir)

        # Run the function
        result = ensure_gitignore_configured(quiet=True)

        assert result is True

        # .gitignore should be created in current directory
        gitignore_path = no_git_dir / ".gitignore"
        assert gitignore_path.exists()
        content = gitignore_path.read_text()
        assert ".spec/" in content
