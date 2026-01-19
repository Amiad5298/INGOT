"""Tests for spec.integrations.git module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from specflow.integrations.git import (
    DiffResult,
    DirtyStateAction,
    is_git_repo,
    is_dirty,
    has_untracked_files,
    has_any_changes,
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


class TestHasUntrackedFiles:
    """Tests for has_untracked_files function."""

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_true_when_untracked_files_exist(self, mock_run):
        """Returns True when there are untracked files."""
        mock_run.return_value = MagicMock(returncode=0, stdout="new_file.txt\nanother.py")

        result = has_untracked_files()

        assert result is True
        mock_run.assert_called_once()

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_false_when_no_untracked_files(self, mock_run):
        """Returns False when there are no untracked files."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        result = has_untracked_files()

        assert result is False

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_false_on_git_error(self, mock_run):
        """Returns False when git command fails."""
        mock_run.return_value = MagicMock(returncode=128, stdout="")

        result = has_untracked_files()

        assert result is False

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_false_on_exception(self, mock_run):
        """Returns False when exception occurs."""
        mock_run.side_effect = Exception("Git not found")

        result = has_untracked_files()

        assert result is False


class TestHasAnyChanges:
    """Tests for has_any_changes function."""

    @patch("specflow.integrations.git.has_untracked_files")
    @patch("specflow.integrations.git.is_dirty")
    def test_returns_true_when_dirty(self, mock_dirty, mock_untracked):
        """Returns True when repo is dirty (staged/unstaged changes)."""
        mock_dirty.return_value = True
        mock_untracked.return_value = False

        result = has_any_changes()

        assert result is True

    @patch("specflow.integrations.git.has_untracked_files")
    @patch("specflow.integrations.git.is_dirty")
    def test_returns_true_when_untracked_only(self, mock_dirty, mock_untracked):
        """Returns True when only untracked files exist (critical test case)."""
        mock_dirty.return_value = False
        mock_untracked.return_value = True

        result = has_any_changes()

        assert result is True

    @patch("specflow.integrations.git.has_untracked_files")
    @patch("specflow.integrations.git.is_dirty")
    def test_returns_true_when_both_dirty_and_untracked(self, mock_dirty, mock_untracked):
        """Returns True when both dirty and untracked files exist."""
        mock_dirty.return_value = True
        mock_untracked.return_value = True

        result = has_any_changes()

        assert result is True

    @patch("specflow.integrations.git.has_untracked_files")
    @patch("specflow.integrations.git.is_dirty")
    def test_returns_false_when_clean(self, mock_dirty, mock_untracked):
        """Returns False when repo is clean with no untracked files."""
        mock_dirty.return_value = False
        mock_untracked.return_value = False

        result = has_any_changes()

        assert result is False


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
    """Tests for get_diff_from_baseline function (returns DiffResult)."""

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_diff_result_with_content(self, mock_run):
        """Returns DiffResult with diff content from baseline commit."""
        # Mock all the subprocess calls that get_diff_from_baseline makes
        # Order: committed diff, staged diff, unstaged diff, staged files, unstaged files,
        #        committed files, staged stat, unstaged stat, committed stat, untracked
        mock_run.side_effect = [
            # 1. git diff --no-color --no-ext-diff base..HEAD (committed)
            MagicMock(returncode=0, stdout="diff --git a/file.py b/file.py\n+new line", stderr=""),
            # 2. git diff --no-color --no-ext-diff --cached (staged)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 3. git diff --no-color --no-ext-diff (unstaged)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 4. git diff --name-only --cached (staged files)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 5. git diff --name-only (unstaged files)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 6. git diff --name-status base..HEAD (committed files)
            MagicMock(returncode=0, stdout="M\tfile.py", stderr=""),
            # 7. git diff --stat --cached (staged stat)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 8. git diff --stat (unstaged stat)
            MagicMock(returncode=0, stdout="", stderr=""),
            # 9. git diff --stat base..HEAD (committed stat)
            MagicMock(returncode=0, stdout=" file.py | 1 +\n 1 file changed, 1 insertion(+)", stderr=""),
            # 10. git ls-files --others --exclude-standard
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        result = get_diff_from_baseline("abc123")

        assert result.is_success
        assert not result.has_error
        assert "diff --git" in result.diff
        assert result.has_changes
        assert "file.py" in result.changed_files

    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_no_changes_on_empty_diff(self, mock_run):
        """Returns DiffResult with has_changes=False when no changes."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # committed
            MagicMock(returncode=0, stdout="", stderr=""),  # staged
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="", stderr=""),  # committed files
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        result = get_diff_from_baseline("abc123")

        assert result.is_success
        assert not result.has_changes
        assert result.diff == ""

    @patch("specflow.integrations.git.print_warning")
    @patch("specflow.integrations.git.subprocess.run")
    def test_returns_error_on_git_failure(self, mock_run, mock_warning):
        """Returns DiffResult with has_error=True when git command fails."""
        # First call fails with non-zero returncode
        mock_run.return_value = MagicMock(
            returncode=128, stdout="", stderr="fatal: bad revision 'abc123'"
        )

        result = get_diff_from_baseline("abc123")

        assert result.has_error
        assert not result.is_success
        assert "failed" in result.error_message.lower()
        mock_warning.assert_called()

    @patch("specflow.integrations.git.subprocess.run")
    def test_empty_commit_falls_back_to_staged_unstaged_untracked(self, mock_run):
        """Falls back to staged+unstaged+untracked when base_commit is empty."""
        # When no base commit: staged diff, unstaged diff, staged files, unstaged files,
        #                      staged stat, unstaged stat, untracked
        mock_run.side_effect = [
            # 1. git diff --cached (staged)
            MagicMock(returncode=0, stdout="staged diff content", stderr=""),
            # 2. git diff (unstaged)
            MagicMock(returncode=0, stdout="unstaged diff content", stderr=""),
            # 3. git diff --name-only --cached (staged files)
            MagicMock(returncode=0, stdout="staged_file.py", stderr=""),
            # 4. git diff --name-only (unstaged files)
            MagicMock(returncode=0, stdout="unstaged_file.py", stderr=""),
            # 5. git diff --stat --cached (staged stat)
            MagicMock(returncode=0, stdout=" 1 file changed", stderr=""),
            # 6. git diff --stat (unstaged stat)
            MagicMock(returncode=0, stdout=" 1 file changed", stderr=""),
            # 7. git ls-files --others --exclude-standard
            MagicMock(returncode=0, stdout="new_file.txt", stderr=""),
        ]

        with patch("specflow.integrations.git._generate_untracked_file_diff") as mock_gen:
            mock_gen.return_value = "diff --git a/new_file.txt\n+content"

            result = get_diff_from_baseline("")

            assert result.is_success
            assert not result.has_error
            assert result.has_changes
            assert "Staged Changes" in result.diff
            assert "Unstaged Changes" in result.diff
            assert "new_file.txt" in result.untracked_files

    @patch("specflow.integrations.git.subprocess.run")
    def test_empty_commit_none_value_also_falls_back(self, mock_run):
        """None base_commit also falls back to staged+unstaged+untracked."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="staged content", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="file.py", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="1 file changed", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        result = get_diff_from_baseline(None)

        assert result.is_success
        assert "file.py" in result.changed_files

    @patch("specflow.integrations.git.subprocess.run")
    def test_includes_all_change_types(self, mock_run):
        """Includes committed, staged, unstaged changes with section headers."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="committed changes", stderr=""),  # committed diff
            MagicMock(returncode=0, stdout="staged changes", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="unstaged changes", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="M\tfile.py", stderr=""),  # committed files
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout=" file.py | 1 +", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        result = get_diff_from_baseline("abc123")

        assert result.is_success
        assert "Committed Changes" in result.diff
        assert "Staged Changes" in result.diff
        assert "Unstaged Changes" in result.diff
        assert "committed changes" in result.diff
        assert "staged changes" in result.diff
        assert "unstaged changes" in result.diff

    @patch("specflow.integrations.git.subprocess.run")
    def test_includes_untracked_files(self, mock_run):
        """Includes untracked files in diff output."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # committed diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="", stderr=""),  # committed files
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="new_file.txt", stderr=""),  # untracked
        ]

        # We need to mock _generate_untracked_file_diff or create the file
        with patch("specflow.integrations.git._generate_untracked_file_diff") as mock_gen:
            mock_gen.return_value = "diff --git a/new_file.txt\n+content"

            result = get_diff_from_baseline("abc123")

            assert result.is_success
            assert "new_file.txt" in result.untracked_files
            assert result.has_changes  # Untracked files count as changes

    @patch("specflow.integrations.git.print_warning")
    @patch("specflow.integrations.git.subprocess.run")
    def test_handles_exception_gracefully(self, mock_run, mock_warning):
        """Returns DiffResult with error on unexpected exception."""
        mock_run.side_effect = Exception("Unexpected error")

        result = get_diff_from_baseline("abc123")

        assert result.has_error
        assert "Exception" in result.error_message
        mock_warning.assert_called()

    @patch("specflow.integrations.git.subprocess.run")
    def test_populates_diffstat(self, mock_run):
        """Populates diffstat summary in result."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="diff content", stderr=""),  # committed diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="M\tfile.py", stderr=""),  # committed files
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout=" file.py | 10 +++++++---\n 1 file changed, 7 insertions(+), 3 deletions(-)", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        result = get_diff_from_baseline("abc123")

        assert result.is_success
        assert "7 insertions" in result.diffstat
        assert "3 deletions" in result.diffstat




# =============================================================================
# Tests for _parse_name_status_line helper (E1)
# =============================================================================


class TestParseNameStatusLine:
    """Tests for _parse_name_status_line helper function (rename/copy handling)."""

    def test_parses_regular_modified_file(self):
        """Parses regular modified file line."""
        from specflow.integrations.git import _parse_name_status_line

        assert _parse_name_status_line("M\tpath/to/file.py") == "path/to/file.py"

    def test_parses_added_file(self):
        """Parses added file line."""
        from specflow.integrations.git import _parse_name_status_line

        assert _parse_name_status_line("A\tnewfile.py") == "newfile.py"

    def test_parses_deleted_file(self):
        """Parses deleted file line."""
        from specflow.integrations.git import _parse_name_status_line

        assert _parse_name_status_line("D\tremoved.py") == "removed.py"

    def test_parses_rename_returns_new_path(self):
        """Parses rename line - returns destination/new path."""
        from specflow.integrations.git import _parse_name_status_line

        # Rename format: R100\told.py\tnew.py (100% similarity)
        assert _parse_name_status_line("R100\told.py\tnew.py") == "new.py"
        # Partial similarity
        assert _parse_name_status_line("R075\told_name.py\tnew_name.py") == "new_name.py"

    def test_parses_copy_returns_new_path(self):
        """Parses copy line - returns destination/copy path."""
        from specflow.integrations.git import _parse_name_status_line

        # Copy format: C100\tsrc.py\tcopy.py
        assert _parse_name_status_line("C100\tsrc.py\tcopy.py") == "copy.py"
        assert _parse_name_status_line("C050\toriginal.py\tdup.py") == "dup.py"

    def test_handles_paths_with_spaces(self):
        """Handles file paths with spaces."""
        from specflow.integrations.git import _parse_name_status_line

        assert _parse_name_status_line("M\tpath/to/my file.py") == "path/to/my file.py"
        assert _parse_name_status_line("R100\told file.py\tnew file.py") == "new file.py"

    def test_handles_empty_line(self):
        """Returns empty string for empty input."""
        from specflow.integrations.git import _parse_name_status_line

        assert _parse_name_status_line("") == ""


class TestGetDiffFromBaselineCommandSyntax:
    """Tests to verify correct git command syntax in get_diff_from_baseline."""

    @patch("specflow.integrations.git.subprocess.run")
    def test_committed_diff_uses_double_dot_syntax(self, mock_run):
        """Committed diff uses 'base..HEAD' (double dot), not 'base.HEAD' (single dot)."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="diff content", stderr=""),  # committed diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            MagicMock(returncode=0, stdout="M\tfile.py", stderr=""),  # committed files
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        get_diff_from_baseline("abc123")

        # Find the committed diff call (first call with base_commit reference)
        calls = mock_run.call_args_list
        committed_diff_call = calls[0]  # First call is committed diff
        committed_files_call = calls[5]  # 6th call is committed files (name-status)
        committed_stat_call = calls[8]  # 9th call is committed stat

        # Verify committed diff uses ..HEAD (double dot)
        diff_cmd = committed_diff_call[0][0]  # args[0] is the command list
        assert "abc123..HEAD" in diff_cmd, f"Expected 'abc123..HEAD' in {diff_cmd}"
        assert "abc123.HEAD" not in diff_cmd, f"Found invalid 'abc123.HEAD' in {diff_cmd}"

        # Verify committed name-status uses ..HEAD (double dot)
        name_status_cmd = committed_files_call[0][0]
        assert "abc123..HEAD" in name_status_cmd, f"Expected 'abc123..HEAD' in {name_status_cmd}"
        assert "abc123.HEAD" not in name_status_cmd, f"Found invalid 'abc123.HEAD' in {name_status_cmd}"

        # Verify committed stat uses ..HEAD (double dot)
        stat_cmd = committed_stat_call[0][0]
        assert "abc123..HEAD" in stat_cmd, f"Expected 'abc123..HEAD' in {stat_cmd}"
        assert "abc123.HEAD" not in stat_cmd, f"Found invalid 'abc123.HEAD' in {stat_cmd}"


class TestGetDiffFromBaselineRenameHandling:
    """Tests for rename/copy handling in get_diff_from_baseline."""

    @patch("specflow.integrations.git.subprocess.run")
    def test_changed_files_contains_only_new_path_for_renames(self, mock_run):
        """For renames, changed_files contains only the destination path."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # committed diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged diff
            MagicMock(returncode=0, stdout="", stderr=""),  # staged files
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged files
            # Committed files with rename
            MagicMock(returncode=0, stdout="R100\told_name.py\tnew_name.py\nM\tother.py", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),  # staged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # unstaged stat
            MagicMock(returncode=0, stdout="", stderr=""),  # committed stat
            MagicMock(returncode=0, stdout="", stderr=""),  # untracked
        ]

        result = get_diff_from_baseline("abc123")

        assert result.is_success
        # Should have only the NEW path, not "old_name.py\tnew_name.py"
        assert "new_name.py" in result.changed_files
        assert "other.py" in result.changed_files
        # Old path should NOT be in the list
        assert "old_name.py" not in result.changed_files
        # The buggy substring should NOT appear
        assert "old_name.py\tnew_name.py" not in result.changed_files
