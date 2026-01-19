"""Tests for spec.integrations.git module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from specflow.integrations.git import (
    DirtyStateAction,
    is_git_repo,
    is_dirty,
    get_current_branch,
    get_current_commit,
    get_status_short,
    branch_exists,
    create_branch,
    checkout_branch,
    add_to_gitignore,
    create_checkpoint_commit,
    squash_commits,
    has_changes,
    revert_changes,
    get_diff_from_baseline,
)


class TestIsGitRepo:
    """Tests for is_git_repo function."""

    def test_returns_true_in_git_repo(self, mock_subprocess):
        """Returns True when in a git repository."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        result = is_git_repo()
        
        assert result is True

    def test_returns_false_outside_git_repo(self, mock_subprocess):
        """Returns False when not in a git repository."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(128, "git")
        
        result = is_git_repo()
        
        assert result is False


class TestIsDirty:
    """Tests for is_dirty function."""

    def test_returns_false_when_clean(self, mock_subprocess):
        """Returns False when no uncommitted changes."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        result = is_dirty()
        
        assert result is False

    def test_returns_true_with_unstaged_changes(self, mock_subprocess):
        """Returns True when there are unstaged changes."""
        # First call (unstaged) returns 1, second call (staged) returns 0
        mock_subprocess.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
        ]
        
        result = is_dirty()
        
        assert result is True

    def test_returns_true_with_staged_changes(self, mock_subprocess):
        """Returns True when there are staged changes."""
        # First call (unstaged) returns 0, second call (staged) returns 1
        mock_subprocess.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1),
        ]
        
        result = is_dirty()
        
        assert result is True


class TestGetCurrentBranch:
    """Tests for get_current_branch function."""

    def test_returns_branch_name(self, mock_subprocess):
        """Returns current branch name."""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="main\n",
        )
        
        result = get_current_branch()
        
        assert result == "main"


class TestGetCurrentCommit:
    """Tests for get_current_commit function."""

    def test_returns_commit_hash(self, mock_subprocess):
        """Returns current commit hash."""
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout="abc123def456\n",
        )
        
        result = get_current_commit()
        
        assert result == "abc123def456"


class TestBranchExists:
    """Tests for branch_exists function."""

    def test_returns_true_when_exists(self, mock_subprocess):
        """Returns True when branch exists."""
        mock_subprocess.return_value = MagicMock(returncode=0)
        
        result = branch_exists("feature-branch")
        
        assert result is True

    def test_returns_false_when_not_exists(self, mock_subprocess):
        """Returns False when branch doesn't exist."""
        mock_subprocess.return_value = MagicMock(returncode=1)
        
        result = branch_exists("nonexistent-branch")
        
        assert result is False


class TestCreateBranch:
    """Tests for create_branch function."""

    @patch("specflow.integrations.git.print_success")
    def test_creates_branch_successfully(self, mock_print, mock_subprocess):
        """Creates and checks out new branch."""
        mock_subprocess.return_value = MagicMock(returncode=0, stderr="")
        
        result = create_branch("new-feature")
        
        assert result is True
        mock_print.assert_called_once()

    @patch("specflow.integrations.git.print_error")
    def test_returns_false_on_failure(self, mock_print, mock_subprocess):
        """Returns False when branch creation fails."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(
            128, "git", stderr="branch already exists"
        )
        
        result = create_branch("existing-branch")
        
        assert result is False


class TestAddToGitignore:
    """Tests for add_to_gitignore function."""

    @patch("specflow.integrations.git.print_success")
    def test_adds_pattern_to_new_file(self, mock_print, tmp_path, monkeypatch):
        """Creates .gitignore and adds pattern."""
        monkeypatch.chdir(tmp_path)
        
        add_to_gitignore("*.log")
        
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert "*.log" in gitignore.read_text()

    @patch("specflow.integrations.git.print_success")
    def test_adds_pattern_to_existing_file(self, mock_print, tmp_path, monkeypatch):
        """Appends pattern to existing .gitignore."""
        monkeypatch.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")
        
        add_to_gitignore("*.log")
        
        content = gitignore.read_text()
        assert "*.pyc" in content
        assert "*.log" in content

    def test_skips_if_pattern_exists(self, tmp_path, monkeypatch):
        """Doesn't add duplicate pattern."""
        monkeypatch.chdir(tmp_path)
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n")

        add_to_gitignore("*.log")

        content = gitignore.read_text()
        assert content.count("*.log") == 1


class TestGetDiffFromBaseline:
    """Tests for get_diff_from_baseline function."""

    @patch("specflow.integrations.git.is_dirty")
    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_diff_content(self, mock_run, mock_is_dirty):
        """Returns diff content from baseline commit."""
        mock_is_dirty.return_value = False
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n+new line",
        )

        result = get_diff_from_baseline("abc123")

        assert "diff --git" in result
        # Check that the diff command was called with the base commit
        diff_calls = [c for c in mock_run.call_args_list if "abc123" in str(c)]
        assert len(diff_calls) == 1
        call_args = diff_calls[0][0][0]
        assert "abc123" in call_args

    @patch("specflow.integrations.git.is_dirty")
    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_empty_string_on_empty_diff(self, mock_run, mock_is_dirty):
        """Returns empty string when no changes."""
        mock_is_dirty.return_value = False
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
        )

        result = get_diff_from_baseline("abc123")

        assert result == ""

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_empty_string_on_error(self, mock_run):
        """Returns empty string when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_diff_from_baseline("abc123")

        assert result == ""

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_empty_string_for_empty_commit(self, mock_run):
        """Returns empty string when base_commit is empty."""
        result = get_diff_from_baseline("")

        assert result == ""
        mock_run.assert_not_called()

    @patch("specflow.integrations.git.is_dirty")
    @patch("specflow.integrations.git.subprocess.run")
    def test_includes_staged_changes_when_dirty(self, mock_run, mock_is_dirty):
        """Includes staged changes when working tree is dirty."""
        mock_is_dirty.return_value = True
        # Return different output for each call
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="committed changes"),  # git diff base HEAD
            MagicMock(returncode=0, stdout="staged changes"),     # git diff --cached
            MagicMock(returncode=0, stdout="unstaged changes"),   # git diff
        ]

        result = get_diff_from_baseline("abc123")

        assert "committed changes" in result
        assert "staged changes" in result
        assert "unstaged changes" in result
        # Should have 3 subprocess calls
        assert mock_run.call_count == 3

