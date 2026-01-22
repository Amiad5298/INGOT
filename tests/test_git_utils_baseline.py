"""Tests for baseline-anchored diff functionality in git_utils.py.

These tests use a temporary git repository fixture to validate:
- Baseline capture and reuse
- Diffs exclude unrelated changes
- Dirty working tree policy
- Smart diff fallback with baseline
- Binary file handling in diffs
"""

import subprocess
from pathlib import Path

import pytest

from spec.workflow.git_utils import (
    DirtyTreePolicy,
    DirtyWorkingTreeError,
    capture_baseline,
    check_dirty_working_tree,
    filter_binary_files_from_diff,
    get_diff_from_baseline,
    get_smart_diff_from_baseline,
    get_working_tree_diff_from_baseline,
    parse_stat_file_count,
    parse_stat_total_lines,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path, monkeypatch):
    """Create a temporary git repository for testing.

    Yields the repo path and provides helper functions.
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    monkeypatch.chdir(repo_path)

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repository\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    class RepoHelper:
        path = repo_path

        @staticmethod
        def create_file(name: str, content: str) -> Path:
            """Create a file in the repo."""
            file_path = repo_path / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            return file_path

        @staticmethod
        def commit_file(name: str, content: str, message: str) -> str:
            """Create, add, and commit a file. Returns commit SHA."""
            RepoHelper.create_file(name, content)
            subprocess.run(["git", "add", name], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

        @staticmethod
        def get_head() -> str:
            """Get current HEAD SHA."""
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip()

    yield RepoHelper


class TestCaptureBaseline:
    """Tests for capture_baseline function."""

    def test_captures_current_head(self, temp_git_repo):
        """Captures the current HEAD commit SHA."""
        expected_head = temp_git_repo.get_head()
        baseline = capture_baseline()
        assert baseline == expected_head

    def test_captures_after_new_commit(self, temp_git_repo):
        """Captures updated HEAD after a new commit."""
        old_head = temp_git_repo.get_head()
        new_sha = temp_git_repo.commit_file("new.txt", "content", "Add new file")
        baseline = capture_baseline()

        assert baseline == new_sha
        assert baseline != old_head


class TestCheckDirtyWorkingTree:
    """Tests for check_dirty_working_tree function."""

    def test_clean_tree_returns_true(self, temp_git_repo):
        """Returns True when working tree is clean."""
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_dirty_tree_raises_with_fail_fast(self, temp_git_repo):
        """Raises DirtyWorkingTreeError when tree is dirty and policy is FAIL_FAST."""
        temp_git_repo.create_file("dirty.txt", "uncommitted")

        with pytest.raises(DirtyWorkingTreeError) as exc_info:
            check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)

        assert "uncommitted changes" in str(exc_info.value).lower()
        assert "dirty.txt" in str(exc_info.value)

    def test_dirty_tree_warns_with_continue(self, temp_git_repo, capsys):
        """Returns False and warns when tree is dirty and policy is WARN_AND_CONTINUE."""
        temp_git_repo.create_file("dirty.txt", "uncommitted")

        result = check_dirty_working_tree(policy=DirtyTreePolicy.WARN_AND_CONTINUE)

        assert result is False

    def test_staged_changes_detected(self, temp_git_repo):
        """Detects staged changes as dirty."""
        temp_git_repo.create_file("staged.txt", "content")
        subprocess.run(["git", "add", "staged.txt"], check=True, capture_output=True)

        with pytest.raises(DirtyWorkingTreeError):
            check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)


class TestWorkflowArtifactFiltering:
    """Tests for workflow artifact exclusion from dirty tree checks.

    Workflow artifacts (.spec/, .augment/, specs/, .DS_Store) are
    excluded from dirty tree checks because they are created by Steps 1-2
    and should not block Step 3 execution.
    """

    def test_is_workflow_artifact_spec_dir(self):
        """Recognizes .spec/ directory as workflow artifact."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact(".spec/") is True
        assert _is_workflow_artifact(".spec/runs/log.txt") is True
        assert _is_workflow_artifact(".spec") is True

    def test_is_workflow_artifact_augment_dir(self):
        """Recognizes .augment/ directory as workflow artifact."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact(".augment/") is True
        assert _is_workflow_artifact(".augment/agents/spec-planner.md") is True
        assert _is_workflow_artifact(".augment") is True

    def test_is_workflow_artifact_specs_dir(self):
        """Recognizes specs/ directory as workflow artifact."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact("specs/") is True
        assert _is_workflow_artifact("specs/TICKET-123-plan.md") is True
        assert _is_workflow_artifact("specs") is True

    def test_is_workflow_artifact_ds_store(self):
        """Recognizes .DS_Store as workflow artifact."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact(".DS_Store") is True

    def test_is_workflow_artifact_non_artifact(self):
        """Correctly identifies non-artifact paths."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact("src/main.py") is False
        assert _is_workflow_artifact("README.md") is False
        assert _is_workflow_artifact("tests/test_foo.py") is False
        assert _is_workflow_artifact("config.yaml") is False

    def test_untracked_spec_dir_ignored(self, temp_git_repo):
        """Untracked .spec/ files do not trigger dirty tree error."""
        spec_dir = temp_git_repo.path / ".spec" / "runs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "log.txt").write_text("log content")

        # Should not raise - .spec/ is excluded
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_untracked_augment_dir_ignored(self, temp_git_repo):
        """Untracked .augment/ files do not trigger dirty tree error."""
        augment_dir = temp_git_repo.path / ".augment" / "agents"
        augment_dir.mkdir(parents=True)
        (augment_dir / "spec-planner.md").write_text("agent content")

        # Should not raise - .augment/ is excluded
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_untracked_specs_dir_ignored(self, temp_git_repo):
        """Untracked specs/ files do not trigger dirty tree error."""
        specs_dir = temp_git_repo.path / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "TICKET-123-plan.md").write_text("plan content")
        (specs_dir / "TICKET-123-tasklist.md").write_text("tasklist content")

        # Should not raise - specs/ is excluded
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_untracked_ds_store_ignored(self, temp_git_repo):
        """Untracked .DS_Store does not trigger dirty tree error."""
        (temp_git_repo.path / ".DS_Store").write_text("ds store content")

        # Should not raise - .DS_Store is excluded
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_mixed_artifacts_and_real_changes_detected(self, temp_git_repo):
        """Real changes are detected even when artifacts are present."""
        # Create workflow artifacts (should be ignored)
        specs_dir = temp_git_repo.path / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "plan.md").write_text("plan")

        augment_dir = temp_git_repo.path / ".augment"
        augment_dir.mkdir(parents=True)
        (augment_dir / "agent.md").write_text("agent")

        # Create a real change (should be detected)
        temp_git_repo.create_file("real_change.py", "code")

        with pytest.raises(DirtyWorkingTreeError) as exc_info:
            check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)

        # Should mention real change but not artifacts
        error_msg = str(exc_info.value)
        assert "real_change.py" in error_msg
        assert "specs/" not in error_msg
        assert ".augment/" not in error_msg

    def test_only_artifacts_present_is_clean(self, temp_git_repo):
        """Tree with only workflow artifacts is considered clean."""
        # Create multiple workflow artifacts
        (temp_git_repo.path / ".DS_Store").write_text("ds")

        specs_dir = temp_git_repo.path / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "plan.md").write_text("plan")

        spec_dir = temp_git_repo.path / ".spec" / "runs"
        spec_dir.mkdir(parents=True)
        (spec_dir / "log.txt").write_text("log")

        augment_dir = temp_git_repo.path / ".augment" / "agents"
        augment_dir.mkdir(parents=True)
        (augment_dir / "spec-planner.md").write_text("agent")

        # Should be clean - only artifacts present
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_staged_artifact_ignored(self, temp_git_repo):
        """Staged workflow artifacts do not trigger dirty tree error."""
        specs_dir = temp_git_repo.path / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "plan.md").write_text("plan content")

        # Stage the artifact
        subprocess.run(["git", "add", "specs/plan.md"], check=True, capture_output=True)

        # Should not raise - staged artifact is excluded
        result = check_dirty_working_tree(policy=DirtyTreePolicy.FAIL_FAST)
        assert result is True

    def test_is_workflow_artifact_gitignore(self):
        """Recognizes .gitignore as workflow artifact (modified by ensure_gitignore_configured)."""
        from spec.workflow.git_utils import _is_workflow_artifact

        assert _is_workflow_artifact(".gitignore") is True

    def test_workflow_artifact_paths_constant_exported(self):
        """WORKFLOW_ARTIFACT_PATHS constant is exported."""
        from spec.workflow.git_utils import WORKFLOW_ARTIFACT_PATHS

        assert ".spec/" in WORKFLOW_ARTIFACT_PATHS
        assert ".augment/" in WORKFLOW_ARTIFACT_PATHS
        assert "specs/" in WORKFLOW_ARTIFACT_PATHS
        assert ".DS_Store" in WORKFLOW_ARTIFACT_PATHS
        assert ".gitignore" in WORKFLOW_ARTIFACT_PATHS


class TestGetDiffFromBaseline:
    """Tests for get_diff_from_baseline function."""

    def test_shows_changes_since_baseline(self, temp_git_repo):
        """Shows committed changes since baseline."""
        baseline = capture_baseline()
        temp_git_repo.commit_file("new_file.py", "def hello():\n    pass\n", "Add function")

        diff_output, git_error = get_diff_from_baseline(baseline)

        assert not git_error
        assert "new_file.py" in diff_output
        assert "def hello():" in diff_output

    def test_empty_diff_when_no_changes(self, temp_git_repo):
        """Returns empty diff when no changes since baseline."""
        baseline = capture_baseline()

        diff_output, git_error = get_diff_from_baseline(baseline)

        assert not git_error
        assert diff_output.strip() == ""

    def test_excludes_pre_baseline_changes(self, temp_git_repo):
        """Pre-baseline changes are not included in diff."""
        # Create a file BEFORE baseline
        temp_git_repo.commit_file("before_baseline.txt", "old content", "Old commit")
        baseline = capture_baseline()

        # Create a file AFTER baseline
        temp_git_repo.commit_file("after_baseline.txt", "new content", "New commit")

        diff_output, git_error = get_diff_from_baseline(baseline)

        assert not git_error
        assert "after_baseline.txt" in diff_output
        assert "before_baseline.txt" not in diff_output


class TestGetWorkingTreeDiffFromBaseline:
    """Tests for get_working_tree_diff_from_baseline function."""

    def test_includes_uncommitted_changes_to_tracked_files(self, temp_git_repo):
        """Includes uncommitted changes to tracked files in diff."""
        # Create and commit a file first (so it's tracked)
        temp_git_repo.commit_file("tracked.txt", "original content", "Add tracked file")
        baseline = capture_baseline()

        # Modify the tracked file without committing
        temp_git_repo.create_file("tracked.txt", "modified content")

        diff_output, git_error = get_working_tree_diff_from_baseline(baseline)

        assert not git_error
        assert "tracked.txt" in diff_output
        assert "modified content" in diff_output

    def test_includes_staged_new_files(self, temp_git_repo):
        """Includes staged new files in diff."""
        baseline = capture_baseline()

        # Create and stage a new file
        temp_git_repo.create_file("staged_new.py", "new_content = True")
        subprocess.run(["git", "add", "staged_new.py"], check=True, capture_output=True)

        diff_output, git_error = get_working_tree_diff_from_baseline(baseline)

        assert not git_error
        assert "staged_new.py" in diff_output
        assert "new_content = True" in diff_output

    def test_includes_both_committed_and_staged(self, temp_git_repo):
        """Includes both committed and staged changes."""
        baseline = capture_baseline()
        temp_git_repo.commit_file("committed.py", "committed = True", "Commit file")

        # Stage a new file
        temp_git_repo.create_file("staged.py", "staged = True")
        subprocess.run(["git", "add", "staged.py"], check=True, capture_output=True)

        diff_output, git_error = get_working_tree_diff_from_baseline(baseline)

        assert not git_error
        assert "committed.py" in diff_output
        assert "staged.py" in diff_output


class TestSmartDiffFromBaseline:
    """Tests for get_smart_diff_from_baseline function."""

    def test_returns_full_diff_for_small_changes(self, temp_git_repo):
        """Returns full diff when changes are small."""
        baseline = capture_baseline()
        temp_git_repo.commit_file("small.txt", "small change", "Small commit")

        diff_output, is_truncated, git_error = get_smart_diff_from_baseline(baseline)

        assert not git_error
        assert not is_truncated
        assert "small.txt" in diff_output
        assert "small change" in diff_output

    def test_returns_stat_only_for_large_changes(self, temp_git_repo):
        """Returns stat-only when changes exceed thresholds."""
        baseline = capture_baseline()

        # Create many files to exceed max_files threshold
        for i in range(25):
            temp_git_repo.commit_file(f"file{i}.txt", f"content {i}", f"Add file {i}")

        diff_output, is_truncated, git_error = get_smart_diff_from_baseline(
            baseline, max_files=20
        )

        assert not git_error
        assert is_truncated
        assert "Large Changeset" in diff_output
        assert "files changed" in diff_output

    def test_excludes_dirty_tree_from_committed_diff(self, temp_git_repo):
        """Excludes uncommitted changes when include_working_tree=False."""
        # Create dirty state BEFORE baseline
        temp_git_repo.create_file("pre_dirty.txt", "dirty before")
        subprocess.run(["git", "add", "pre_dirty.txt"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "commit dirty"], check=True, capture_output=True)

        baseline = capture_baseline()

        # Create committed change after baseline
        temp_git_repo.commit_file("committed_after.txt", "after baseline", "After baseline")

        # Create uncommitted change (should be excluded)
        temp_git_repo.create_file("uncommitted.txt", "uncommitted content")

        diff_output, is_truncated, git_error = get_smart_diff_from_baseline(
            baseline, include_working_tree=False
        )

        assert not git_error
        assert "committed_after.txt" in diff_output
        assert "uncommitted.txt" not in diff_output


class TestFilterBinaryFiles:
    """Tests for filter_binary_files_from_diff function."""

    def test_filters_binary_file_markers(self):
        """Replaces binary file markers with readable placeholders."""
        diff_with_binary = """diff --git a/image.png b/image.png
Binary files a/image.png and b/image.png differ
diff --git a/text.txt b/text.txt
--- a/text.txt
+++ b/text.txt
@@ -1 +1 @@
-old
+new
"""
        result = filter_binary_files_from_diff(diff_with_binary)

        assert "Binary files" not in result
        assert "[BINARY FILE CHANGED: image.png]" in result
        assert "text.txt" in result
        assert "+new" in result

    def test_handles_multiple_binary_files(self):
        """Handles multiple binary files in diff."""
        diff_output = """Binary files a/a.bin and b/a.bin differ
Binary files a/b.bin and b/b.bin differ
"""
        result = filter_binary_files_from_diff(diff_output)

        assert "[BINARY FILE CHANGED: a.bin]" in result
        assert "[BINARY FILE CHANGED: b.bin]" in result

    def test_no_change_when_no_binary_files(self):
        """Returns unchanged output when no binary files."""
        diff_output = "+++ b/file.txt\n-old\n+new"
        result = filter_binary_files_from_diff(diff_output)
        assert result == diff_output


class TestStatParsing:
    """Tests for stat parsing functions."""

    def test_parse_stat_total_lines(self):
        """Parses total lines from stat output."""
        stat_output = " 5 files changed, 100 insertions(+), 50 deletions(-)"
        assert parse_stat_total_lines(stat_output) == 150

    def test_parse_stat_total_lines_insertions_only(self):
        """Parses insertions-only stat output."""
        stat_output = " 1 file changed, 25 insertions(+)"
        assert parse_stat_total_lines(stat_output) == 25

    def test_parse_stat_total_lines_deletions_only(self):
        """Parses deletions-only stat output."""
        stat_output = " 1 file changed, 10 deletions(-)"
        assert parse_stat_total_lines(stat_output) == 10

    def test_parse_stat_file_count(self):
        """Parses file count from stat output."""
        stat_output = " 5 files changed, 100 insertions(+), 50 deletions(-)"
        assert parse_stat_file_count(stat_output) == 5

    def test_parse_stat_single_file(self):
        """Parses single file stat output."""
        stat_output = " 1 file changed, 10 insertions(+)"
        assert parse_stat_file_count(stat_output) == 1


class TestUntrackedFiles:
    """Tests for untracked file handling in diffs."""

    def test_get_untracked_files_returns_list(self, temp_git_repo):
        """Returns list of untracked files."""
        from spec.workflow.git_utils import get_untracked_files

        # Create untracked files
        temp_git_repo.create_file("untracked1.txt", "content1")
        temp_git_repo.create_file("untracked2.py", "print('hello')")

        untracked = get_untracked_files()

        assert "untracked1.txt" in untracked
        assert "untracked2.py" in untracked
        assert len(untracked) == 2

    def test_get_untracked_files_empty_when_all_tracked(self, temp_git_repo):
        """Returns empty list when no untracked files."""
        from spec.workflow.git_utils import get_untracked_files

        # All files are tracked (initial commit has README.md)
        untracked = get_untracked_files()
        assert untracked == []

    def test_get_untracked_files_excludes_gitignored(self, temp_git_repo):
        """Excludes files matching .gitignore patterns."""
        from spec.workflow.git_utils import get_untracked_files

        # Create .gitignore
        temp_git_repo.create_file(".gitignore", "*.log\n__pycache__/\n")
        subprocess.run(["git", "add", ".gitignore"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add gitignore"], check=True, capture_output=True)

        # Create ignored and non-ignored files
        temp_git_repo.create_file("debug.log", "log content")
        temp_git_repo.create_file("visible.txt", "visible content")

        untracked = get_untracked_files()

        assert "visible.txt" in untracked
        assert "debug.log" not in untracked

    def test_untracked_files_diff_generates_unified_format(self, temp_git_repo):
        """Generates unified diff format for untracked files."""
        from spec.workflow.git_utils import get_untracked_files_diff

        temp_git_repo.create_file("new_file.py", "def hello():\n    pass\n")

        diff = get_untracked_files_diff()

        assert "diff --git a/new_file.py b/new_file.py" in diff
        assert "new file mode" in diff
        assert "+def hello():" in diff
        assert "+    pass" in diff

    def test_untracked_files_diff_stat_only(self, temp_git_repo):
        """Generates stat-like output for untracked files."""
        from spec.workflow.git_utils import get_untracked_files_diff

        temp_git_repo.create_file("file1.txt", "content")
        temp_git_repo.create_file("file2.txt", "content")

        diff = get_untracked_files_diff(stat_only=True)

        assert "file1.txt" in diff
        assert "file2.txt" in diff
        assert "[NEW FILE]" in diff
        assert "2 untracked file(s)" in diff

    def test_untracked_binary_file_marked(self, temp_git_repo):
        """Binary untracked files are marked with placeholder."""
        from spec.workflow.git_utils import get_untracked_files_diff

        # Create a binary file (contains null bytes)
        binary_path = temp_git_repo.path / "image.bin"
        binary_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        diff = get_untracked_files_diff()

        assert "[BINARY FILE ADDED: image.bin]" in diff

    def test_working_tree_diff_includes_untracked(self, temp_git_repo):
        """Working tree diff includes untracked files by default."""
        baseline = capture_baseline()

        # Create an untracked file
        temp_git_repo.create_file("new_untracked.py", "x = 1\n")

        diff_output, git_error = get_working_tree_diff_from_baseline(baseline)

        assert not git_error
        assert "new_untracked.py" in diff_output
        assert "+x = 1" in diff_output

    def test_working_tree_diff_excludes_untracked_when_disabled(self, temp_git_repo):
        """Working tree diff excludes untracked files when disabled."""
        baseline = capture_baseline()

        # Create an untracked file
        temp_git_repo.create_file("new_untracked.py", "x = 1\n")

        diff_output, git_error = get_working_tree_diff_from_baseline(
            baseline, include_untracked=False
        )

        assert not git_error
        assert "new_untracked.py" not in diff_output

    def test_smart_diff_includes_untracked(self, temp_git_repo):
        """Smart diff includes untracked files by default."""
        baseline = capture_baseline()

        # Create an untracked file
        temp_git_repo.create_file("smart_untracked.txt", "smart content\n")

        diff_output, is_truncated, git_error = get_smart_diff_from_baseline(baseline)

        assert not git_error
        assert not is_truncated
        assert "smart_untracked.txt" in diff_output
        assert "+smart content" in diff_output

    def test_smart_diff_excludes_untracked_when_disabled(self, temp_git_repo):
        """Smart diff excludes untracked files when disabled."""
        baseline = capture_baseline()

        # Create an untracked file
        temp_git_repo.create_file("smart_untracked.txt", "smart content\n")

        diff_output, is_truncated, git_error = get_smart_diff_from_baseline(
            baseline, include_untracked=False
        )

        assert not git_error
        assert "smart_untracked.txt" not in diff_output

