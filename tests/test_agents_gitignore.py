"""Tests for INGOT gitignore management in agents.py.

Tests the ensure_gitignore_configured() function and related utilities
that manage the target project's .gitignore file.
"""

from unittest.mock import patch

from ingot.integrations.agents import (
    INGOT_GITIGNORE_MARKER,
    INGOT_GITIGNORE_PATTERNS,
    _check_gitignore_has_pattern,
    ensure_gitignore_configured,
)


class TestCheckGitignoreHasPattern:
    def test_finds_exact_pattern_match(self):
        content = "*.pyc\n.ingot/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".ingot/") is True

    def test_finds_pattern_with_surrounding_whitespace(self):
        content = "*.pyc\n  .ingot/  \n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".ingot/") is True

    def test_does_not_match_partial_pattern(self):
        content = "*.pyc\n.ingot-backup/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".ingot/") is False

    def test_does_not_match_commented_pattern(self):
        content = "*.pyc\n# .ingot/\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".ingot/") is False

    def test_finds_log_pattern(self):
        content = "*.pyc\n*.log\n__pycache__/"
        assert _check_gitignore_has_pattern(content, "*.log") is True

    def test_returns_false_for_missing_pattern(self):
        content = "*.pyc\n__pycache__/"
        assert _check_gitignore_has_pattern(content, ".ingot/") is False

    def test_handles_empty_content(self):
        assert _check_gitignore_has_pattern("", ".ingot/") is False

    def test_handles_only_comments(self):
        content = "# Python\n# Ignore pyc files"
        assert _check_gitignore_has_pattern(content, ".ingot/") is False


class TestGitignorePatternsConfiguration:
    """Tests for INGOT_GITIGNORE_PATTERNS configuration.

    These tests verify the patterns list is correctly configured to:
    - Ignore runtime artifacts (.ingot/, *.log)
    - NOT ignore user-visible files (specs/ directory with plan/tasklist .md files)
    """

    def test_patterns_include_spec_directory(self):
        assert ".ingot/" in INGOT_GITIGNORE_PATTERNS

    def test_patterns_include_log_files(self):
        assert "*.log" in INGOT_GITIGNORE_PATTERNS

    def test_patterns_do_not_include_specs_directory(self):
        assert "specs/" not in INGOT_GITIGNORE_PATTERNS
        assert "specs" not in INGOT_GITIGNORE_PATTERNS

    def test_patterns_only_contain_expected_entries(self):
        expected_patterns = [".ingot/", "*.log"]
        assert INGOT_GITIGNORE_PATTERNS == expected_patterns


class TestEnsureGitignoreConfigured:
    def test_creates_gitignore_if_not_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # File should not exist initially
        assert not gitignore_path.exists()

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        assert gitignore_path.exists()

        content = gitignore_path.read_text()
        assert INGOT_GITIGNORE_MARKER in content
        for pattern in INGOT_GITIGNORE_PATTERNS:
            assert pattern in content

    def test_appends_to_existing_gitignore(self, tmp_path, monkeypatch):
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

        # INGOT patterns should be added
        assert INGOT_GITIGNORE_MARKER in content
        for pattern in INGOT_GITIGNORE_PATTERNS:
            assert pattern in content

    def test_idempotent_does_not_duplicate(self, tmp_path, monkeypatch):
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
        for pattern in INGOT_GITIGNORE_PATTERNS:
            assert second_content.count(pattern) == 1

    def test_preserves_existing_content_exactly(self, tmp_path, monkeypatch):
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
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with INGOT patterns already present
        existing_content = "*.pyc\n.ingot/\n*.log\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Content should be unchanged
        assert content == existing_content

    def test_adds_only_missing_patterns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with only one INGOT pattern
        existing_content = "*.pyc\n.ingot/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # .ingot/ should appear only once (not duplicated)
        assert content.count(".ingot/") == 1
        # *.log should be added
        assert "*.log" in content

    def test_handles_file_without_trailing_newline(self, tmp_path, monkeypatch):
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
        for pattern in INGOT_GITIGNORE_PATTERNS:
            assert pattern in lines or any(line.strip() == pattern for line in lines)

    def test_adds_marker_comment_only_once(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with marker but only one pattern
        existing_content = f"*.pyc\n{INGOT_GITIGNORE_MARKER}\n.ingot/\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # Marker should appear only once
        assert content.count(INGOT_GITIGNORE_MARKER) == 1
        # Missing pattern should be added
        assert "*.log" in content

    def test_returns_true_when_already_configured(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create fully configured .gitignore
        gitignore_path.write_text(".ingot/\n*.log\n")

        result = ensure_gitignore_configured(quiet=True)
        assert result is True

    @patch("ingot.integrations.agents.print_info")
    def test_prints_info_when_not_quiet(self, mock_print, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        ensure_gitignore_configured(quiet=False)

        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert ".gitignore" in call_args
        assert "INGOT" in call_args

    def test_does_not_modify_patterns_in_comments(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        gitignore_path = tmp_path / ".gitignore"

        # Create .gitignore with patterns only in comments
        existing_content = "# Ignore .ingot/ for logs\n# *.log files\n"
        gitignore_path.write_text(existing_content)

        result = ensure_gitignore_configured(quiet=True)

        assert result is True
        content = gitignore_path.read_text()

        # All patterns should be added as actual rules (not just comments)
        lines = [line.strip() for line in content.split("\n") if not line.strip().startswith("#")]
        assert ".ingot/" in lines
        assert "*.log" in lines


class TestRepoRootDetection:
    def test_updates_gitignore_at_repo_root_from_subdir(self, tmp_path, monkeypatch):
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
        assert ".ingot/" in content
        assert "*.log" in content

        # No .gitignore should be created in the subdirectory
        assert not (subdir / ".gitignore").exists()

    def test_falls_back_to_cwd_when_not_in_git_repo(self, tmp_path, monkeypatch):
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
        assert ".ingot/" in content
