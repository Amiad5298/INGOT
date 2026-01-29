"""Git operations for SPEC.

This module provides git-related functionality including branch management,
commit operations, dirty state handling, and checkpoint commit squashing.
"""

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from spec.utils.console import print_error, print_info, print_success, print_warning
from spec.utils.logging import log_command


@dataclass
class DiffResult:
    """Result of a git diff operation.

    Attributes:
        diff: The diff content (empty string if no changes or error)
        has_error: True if git command failed
        error_message: Description of the error if has_error is True
        changed_files: List of changed file paths (from git diff --name-status)
        diffstat: Summary of changes (insertions/deletions)
        untracked_files: List of untracked file paths
    """

    diff: str = ""
    has_error: bool = False
    error_message: str = ""
    changed_files: list[str] = None  # type: ignore[assignment]
    diffstat: str = ""
    untracked_files: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.changed_files is None:
            self.changed_files = []
        if self.untracked_files is None:
            self.untracked_files = []

    @property
    def has_changes(self) -> bool:
        """True if there are any changes (diff content, changed files, or untracked)."""
        return bool(self.diff.strip() or self.changed_files or self.untracked_files)

    @property
    def is_success(self) -> bool:
        """True if the diff operation succeeded (even if no changes)."""
        return not self.has_error


class DirtyStateAction(Enum):
    """Actions for handling uncommitted changes."""

    STASH = "stash"
    COMMIT = "commit"
    DISCARD = "discard"
    CONTINUE = "continue"
    ABORT = "abort"


def _parse_name_status_line(line: str) -> str:
    """Parse a git diff --name-status output line and return the filepath.

    Handles regular entries (M/A/D) and rename/copy entries (R/C):
    - Regular: "M\tpath/to/file"  -> "path/to/file"
    - Rename:  "R100\told\tnew"   -> "new" (destination path)
    - Copy:    "C100\tsrc\tcopy"  -> "copy" (destination path)

    Args:
        line: A single line from git diff --name-status output.

    Returns:
        The filepath (for renames/copies, returns the new/destination path).
    """
    parts = line.split("\t")
    # For renames/copies, git outputs: status\told_path\tnew_path
    # We want the last part (new path for R/C, only path for others)
    return parts[-1] if parts else ""


def find_repo_root() -> Path | None:
    """Find the git repository root by looking for .git directory.

    Traverses from current working directory upward until:
    - A .git directory is found (returns that directory)
    - The filesystem root is reached (returns None)

    Returns:
        Path to repository root, or None if not in a repository
    """
    current = Path.cwd()
    while True:
        if (current / ".git").exists():
            return current

        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent

    return None


def is_git_repo() -> bool:
    """Check if current directory is a git repository.

    Returns:
        True if in a git repository
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            check=True,
        )
        log_command("git rev-parse --git-dir", result.returncode)
        return True
    except subprocess.CalledProcessError:
        return False


def is_dirty() -> bool:
    """Check if working directory has uncommitted changes.

    Returns:
        True if there are uncommitted changes (staged or unstaged)
    """
    try:
        # Check unstaged changes
        result1 = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True,
        )
        # Check staged changes
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        return result1.returncode != 0 or result2.returncode != 0
    except subprocess.CalledProcessError:
        return False


def has_untracked_files() -> bool:
    """Check if there are any untracked files (excluding ignored).

    Returns:
        True if there are untracked files
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
        )
        log_command("git ls-files --others --exclude-standard", result.returncode)
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def has_any_changes() -> bool:
    """Check if working directory has any changes (staged, unstaged, or untracked).

    This is a comprehensive check that combines is_dirty() and has_untracked_files().

    Returns:
        True if there are any changes (staged, unstaged, or untracked files)
    """
    return is_dirty() or has_untracked_files()


def get_current_branch() -> str:
    """Get current branch name.

    Returns:
        Current branch name

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    )
    log_command("git branch --show-current", result.returncode)
    return result.stdout.strip()


def get_current_commit() -> str:
    """Get current commit hash.

    Returns:
        Full commit hash

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    log_command("git rev-parse HEAD", result.returncode)
    return result.stdout.strip()


def get_status_short() -> str:
    """Get short git status output.

    Returns:
        Short status output
    """
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True,
        text=True,
    )
    log_command("git status --short", result.returncode)
    return result.stdout


def branch_exists(branch_name: str) -> bool:
    """Check if a branch exists.

    Args:
        branch_name: Name of the branch to check

    Returns:
        True if branch exists
    """
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        capture_output=True,
    )
    return result.returncode == 0


def create_branch(branch_name: str) -> bool:
    """Create and checkout a new branch.

    Args:
        branch_name: Name for the new branch

    Returns:
        True if successful
    """
    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            check=True,
            capture_output=True,
            text=True,
        )
        log_command(f"git checkout -b {branch_name}", result.returncode)
        print_success(f"Created and switched to new branch: {branch_name}")
        return True
    except subprocess.CalledProcessError as e:
        log_command(f"git checkout -b {branch_name}", e.returncode)
        print_error(f"Failed to create branch: {e.stderr}")
        return False


def checkout_branch(branch_name: str) -> bool:
    """Switch to an existing branch.

    Args:
        branch_name: Name of the branch to checkout

    Returns:
        True if successful
    """
    try:
        result = subprocess.run(
            ["git", "checkout", branch_name],
            check=True,
            capture_output=True,
            text=True,
        )
        log_command(f"git checkout {branch_name}", result.returncode)
        print_success(f"Switched to branch: {branch_name}")
        return True
    except subprocess.CalledProcessError as e:
        log_command(f"git checkout {branch_name}", e.returncode)
        print_error(f"Failed to switch branch: {e.stderr}")
        return False


def add_to_gitignore(pattern: str) -> None:
    """Add pattern to .gitignore if not present.

    Args:
        pattern: Pattern to add to .gitignore
    """
    gitignore = Path(".gitignore")

    if gitignore.exists():
        content = gitignore.read_text()
        if pattern in content.splitlines():
            return  # Already present

    with gitignore.open("a") as f:
        f.write(f"\n{pattern}")

    print_success(f"Added to .gitignore: {pattern}")


def create_checkpoint_commit(ticket_id: str, task_name: str) -> str:
    """Create a checkpoint commit for a completed task.

    Args:
        ticket_id: Ticket ID (e.g., PROJ-123)
        task_name: Name of the completed task

    Returns:
        Commit hash (short form)

    Raises:
        subprocess.CalledProcessError: If git command fails
    """
    subprocess.run(["git", "add", "."], check=True)
    commit_msg = f"wip({ticket_id}): {task_name}"
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()[:8]


def squash_commits(base_commit: str, ticket_id: str, tasks: list[str]) -> None:
    """Squash checkpoint commits into a single commit.

    Args:
        base_commit: Commit hash to reset to
        ticket_id: Ticket ID (e.g., PROJ-123)
        tasks: List of completed task names
    """
    if len(tasks) == 1:
        final_msg = f"feat({ticket_id}): {tasks[0]}"
    else:
        task_list = "\n".join(f"- {t}" for t in tasks)
        final_msg = (
            f"feat({ticket_id}): implement {len(tasks)} tasks\n\nCompleted tasks:\n{task_list}"
        )

    subprocess.run(["git", "reset", "--soft", base_commit], check=True)
    subprocess.run(["git", "commit", "-m", final_msg], check=True)
    print_success("Checkpoint commits squashed into single commit")


def handle_dirty_state(context: str, action: DirtyStateAction) -> bool:
    """Handle uncommitted changes based on user selection.

    Args:
        context: Description of pending operation
        action: Selected action from menu

    Returns:
        True if safe to proceed, False if aborted
    """
    # Import here to avoid circular imports
    from spec.ui.prompts import prompt_confirm, prompt_input

    if action == DirtyStateAction.STASH:
        stash_msg = f"spec: auto-stash before {context}"
        subprocess.run(["git", "stash", "push", "-m", stash_msg], check=True)
        print_success("Changes stashed successfully")
        print_info("To restore later: git stash pop")
        return True

    elif action == DirtyStateAction.COMMIT:
        commit_msg = prompt_input("Enter commit message", "WIP: work in progress")
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        print_success("Changes committed successfully")
        return True

    elif action == DirtyStateAction.DISCARD:
        if prompt_confirm("Are you sure you want to discard ALL uncommitted changes?"):
            subprocess.run(["git", "restore", "."], check=True)
            subprocess.run(["git", "clean", "-fd"], check=True)
            print_success("Changes discarded")
            return True
        return False

    elif action == DirtyStateAction.CONTINUE:
        print_warning("Continuing with uncommitted changes (not recommended)")
        return True

    elif action == DirtyStateAction.ABORT:
        print_info(f"Aborting {context}")
        return False

    return False


def stash_changes(message: str = "WIP") -> bool:
    """Stash uncommitted changes.

    Args:
        message: Stash message

    Returns:
        True if stash was successful
    """
    try:
        result = subprocess.run(
            ["git", "stash", "push", "-m", message],
            capture_output=True,
            text=True,
            check=True,
        )
        log_command(f"git stash push -m '{message}'", result.returncode)
        print_success(f"Changes stashed: {message}")
        return True
    except subprocess.CalledProcessError as e:
        log_command(f"git stash push -m '{message}'", e.returncode)
        print_error(f"Failed to stash changes: {e.stderr}")
        return False


def commit_changes(message: str) -> str:
    """Stage all changes and commit.

    Args:
        message: Commit message

    Returns:
        Short commit hash, or empty string on failure
    """
    try:
        # Stage all changes
        subprocess.run(["git", "add", "-A"], check=True)

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            check=True,
        )
        log_command(f"git commit -m '{message}'", result.returncode)

        # Get commit hash
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return hash_result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log_command(f"git commit -m '{message}'", e.returncode)
        return ""


def get_diff_from_baseline(base_commit: str | None) -> DiffResult:
    """Get the git diff from a baseline commit to the current state.

    This includes committed changes, staged changes, unstaged changes,
    and untracked files since the baseline.

    Uses --no-color and --no-ext-diff for clean, parseable output.

    If base_commit is empty/None but repo is dirty, falls back to
    collecting staged + unstaged + untracked changes (no commit-to-commit diff).

    Args:
        base_commit: The baseline commit hash to diff from (can be empty/None)

    Returns:
        DiffResult with diff content, changed files list, diffstat, and error status.
        On error, has_error is True and error_message contains details.
    """
    # Handle missing base_commit - fall back to staged + unstaged + untracked
    no_base_commit = not base_commit or not base_commit.strip()

    diff_sections: list[str] = []
    changed_files: list[str] = []
    untracked_files: list[str] = []
    diffstat = ""

    try:
        # Base git diff flags for clean output
        base_flags = ["--no-color", "--no-ext-diff"]

        # 1. Get committed changes: git diff <base>..HEAD (only if we have a base commit)
        if not no_base_commit:
            committed_result = subprocess.run(
                ["git", "diff", *base_flags, f"{base_commit}..HEAD"],
                capture_output=True,
                text=True,
            )
            log_command(f"git diff {base_commit}..HEAD", committed_result.returncode)

            if committed_result.returncode != 0:
                stderr = (
                    committed_result.stderr.strip() if committed_result.stderr else "unknown error"
                )
                print_warning(f"Failed to compute committed diff: {stderr}")
                return DiffResult(
                    has_error=True,
                    error_message=f"git diff {base_commit}..HEAD failed: {stderr}",
                )

            if committed_result.stdout.strip():
                diff_sections.append("=== Committed Changes ===\n" + committed_result.stdout)

        # 2. Get staged changes: git diff --cached
        staged_result = subprocess.run(
            ["git", "diff", *base_flags, "--cached"],
            capture_output=True,
            text=True,
        )
        log_command("git diff --cached", staged_result.returncode)

        if staged_result.returncode != 0:
            stderr = staged_result.stderr.strip() if staged_result.stderr else "unknown error"
            print_warning(f"Failed to compute staged diff: {stderr}")
            return DiffResult(
                has_error=True,
                error_message=f"git diff --cached failed: {stderr}",
            )

        if staged_result.stdout.strip():
            diff_sections.append("=== Staged Changes ===\n" + staged_result.stdout)

        # 3. Get unstaged changes: git diff
        unstaged_result = subprocess.run(
            ["git", "diff", *base_flags],
            capture_output=True,
            text=True,
        )
        log_command("git diff", unstaged_result.returncode)

        if unstaged_result.returncode != 0:
            stderr = unstaged_result.stderr.strip() if unstaged_result.stderr else "unknown error"
            print_warning(f"Failed to compute unstaged diff: {stderr}")
            return DiffResult(
                has_error=True,
                error_message=f"git diff failed: {stderr}",
            )

        if unstaged_result.stdout.strip():
            diff_sections.append("=== Unstaged Changes ===\n" + unstaged_result.stdout)

        # 4. Get changed files list
        # Always collect staged + unstaged files to capture working tree changes
        # even when base_commit exists (base..HEAD may be empty if no commits yet)
        staged_files_result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
        )
        log_command("git diff --name-only --cached", staged_files_result.returncode)

        unstaged_files_result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
        )
        log_command("git diff --name-only", unstaged_files_result.returncode)

        if staged_files_result.returncode == 0:
            changed_files.extend(
                [f for f in staged_files_result.stdout.strip().split("\n") if f.strip()]
            )
        else:
            stderr = (
                staged_files_result.stderr.strip()
                if staged_files_result.stderr
                else "unknown error"
            )
            print_warning(f"Failed to list staged files: {stderr}")

        if unstaged_files_result.returncode == 0:
            changed_files.extend(
                [f for f in unstaged_files_result.stdout.strip().split("\n") if f.strip()]
            )
        else:
            stderr = (
                unstaged_files_result.stderr.strip()
                if unstaged_files_result.stderr
                else "unknown error"
            )
            print_warning(f"Failed to list unstaged files: {stderr}")

        # Also get committed changes if we have a base commit
        if not no_base_commit:
            name_status_result = subprocess.run(
                ["git", "diff", "--name-status", f"{base_commit}..HEAD"],
                capture_output=True,
                text=True,
            )
            log_command(
                f"git diff --name-status {base_commit}..HEAD", name_status_result.returncode
            )

            if name_status_result.returncode != 0:
                stderr = (
                    name_status_result.stderr.strip()
                    if name_status_result.stderr
                    else "unknown error"
                )
                print_warning(f"Failed to get changed files list: {stderr}")
                # Non-fatal: continue with what we have
            elif name_status_result.stdout.strip():
                changed_files.extend(
                    _parse_name_status_line(line)
                    for line in name_status_result.stdout.strip().split("\n")
                    if line.strip()
                )

        changed_files = list(set(changed_files))  # Deduplicate

        # 5. Get diffstat summary
        # Always include staged + unstaged diffstat
        diffstat_parts = []

        # Staged diffstat
        staged_stat_result = subprocess.run(
            ["git", "diff", "--stat", "--cached"],
            capture_output=True,
            text=True,
        )
        log_command("git diff --stat --cached", staged_stat_result.returncode)

        if staged_stat_result.returncode == 0 and staged_stat_result.stdout.strip():
            diffstat_parts.append("Staged:\n" + staged_stat_result.stdout.strip())

        # Unstaged diffstat
        unstaged_stat_result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
        )
        log_command("git diff --stat", unstaged_stat_result.returncode)

        if unstaged_stat_result.returncode == 0 and unstaged_stat_result.stdout.strip():
            diffstat_parts.append("Unstaged:\n" + unstaged_stat_result.stdout.strip())

        # Committed diffstat (if we have a base commit)
        if not no_base_commit:
            committed_stat_result = subprocess.run(
                ["git", "diff", "--stat", f"{base_commit}..HEAD"],
                capture_output=True,
                text=True,
            )
            log_command(f"git diff --stat {base_commit}..HEAD", committed_stat_result.returncode)

            if committed_stat_result.returncode == 0 and committed_stat_result.stdout.strip():
                diffstat_parts.insert(0, "Committed:\n" + committed_stat_result.stdout.strip())

        diffstat = "\n\n".join(diffstat_parts)

        # 6. Get untracked files: git ls-files --others --exclude-standard
        untracked_result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
        )
        log_command("git ls-files --others --exclude-standard", untracked_result.returncode)

        if untracked_result.returncode != 0:
            stderr = untracked_result.stderr.strip() if untracked_result.stderr else "unknown error"
            print_warning(f"Failed to list untracked files: {stderr}")
            # Non-fatal: continue with empty untracked_files
        elif untracked_result.stdout.strip():
            untracked_files = [f for f in untracked_result.stdout.strip().split("\n") if f.strip()]

            # Generate diff-like content for small text untracked files
            untracked_diff_parts = []
            for filepath in untracked_files:
                untracked_diff_parts.append(_generate_untracked_file_diff(filepath))

            if untracked_diff_parts:
                diff_sections.append("=== Untracked Files ===\n" + "\n".join(untracked_diff_parts))

        diff_output = "\n\n".join(diff_sections).strip()

        return DiffResult(
            diff=diff_output,
            has_error=False,
            changed_files=changed_files,
            diffstat=diffstat,
            untracked_files=untracked_files,
        )

    except Exception as e:
        print_warning(f"Failed to get diff from baseline: {e}")
        return DiffResult(
            has_error=True,
            error_message=f"Exception during diff: {e}",
        )


def _is_doc_file_for_diff(filepath: str) -> bool:
    """Check if a file is a documentation file (for diff content inclusion).

    This is a simple check to determine if we should include full content
    for untracked files. Only documentation files get full content to
    avoid leaking secrets or other sensitive non-doc files.

    Args:
        filepath: Path to the file.

    Returns:
        True if the file appears to be documentation.
    """
    path = Path(filepath)
    # Note: .txt is intentionally excluded to avoid treating config files like
    # requirements.txt, constraints.txt as documentation
    doc_extensions = {".md", ".rst", ".adoc", ".asciidoc"}
    doc_directories = ("docs/", "doc/", "documentation/", "wiki/")
    doc_names = {"README", "CHANGELOG", "CONTRIBUTING", "LICENSE", "AUTHORS", "HISTORY"}

    # Check by extension
    if path.suffix.lower() in doc_extensions:
        return True

    # Check if in a docs directory (but NOT .github/workflows or similar)
    filepath_lower = filepath.lower().replace("\\", "/")
    for pattern in doc_directories:
        if pattern in filepath_lower:
            return True

    # Check by filename stem
    if path.stem.upper() in doc_names:
        return True

    return False


def _generate_untracked_file_diff(filepath: str, max_file_size: int = 50_000) -> str:
    """Generate diff-like output for a single untracked file.

    Only includes full content for documentation files to avoid
    leaking secrets or sensitive information. Non-doc files get
    a filename-only entry.

    Args:
        filepath: Path to the untracked file.
        max_file_size: Max bytes to include content (default 50KB).

    Returns:
        Diff-like string for the file.
    """
    import os

    try:
        if not os.path.isfile(filepath):
            return f"diff --git a/{filepath} b/{filepath}\nnew file (not readable)\n"

        # For non-doc files, only include filename (avoid secrets/noise)
        if not _is_doc_file_for_diff(filepath):
            file_size = os.path.getsize(filepath)
            return (
                f"diff --git a/{filepath} b/{filepath}\n"
                f"new file mode 100644\n"
                f"[NEW FILE: {filepath} ({file_size} bytes) - content omitted (non-doc)]\n"
            )

        file_size = os.path.getsize(filepath)

        if file_size > max_file_size:
            return (
                f"diff --git a/{filepath} b/{filepath}\n"
                f"new file mode 100644\n"
                f"[LARGE FILE: {filepath} ({file_size} bytes) - content omitted]\n"
            )

        # Check if binary by looking for null bytes
        try:
            with open(filepath, "rb") as f:
                sample = f.read(8192)
            if b"\x00" in sample:
                return (
                    f"diff --git a/{filepath} b/{filepath}\n"
                    f"new file mode 100644\n"
                    f"[BINARY FILE: {filepath}]\n"
                )
        except OSError:
            pass

        # Read and format text file (doc files only)
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()

        lines = content.splitlines(keepends=True)
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"

        diff_lines = [
            f"diff --git a/{filepath} b/{filepath}\n",
            "new file mode 100644\n",
            "--- /dev/null\n",
            f"+++ b/{filepath}\n",
            f"@@ -0,0 +1,{len(lines)} @@\n",
        ]
        for line in lines:
            diff_lines.append(f"+{line}")

        return "".join(diff_lines)

    except OSError as e:
        return (
            f"diff --git a/{filepath} b/{filepath}\n"
            f"new file mode 100644\n"
            f"[ERROR READING FILE: {filepath} - {e}]\n"
        )


def get_changed_files_list(base_commit: str) -> tuple[list[str], str]:
    """Get list of changed files and name-status output since base commit.

    Args:
        base_commit: The baseline commit hash

    Returns:
        Tuple of (file_list, name_status_output) where name_status_output
        is the raw git diff --name-status output.
    """
    if not base_commit:
        return [], ""

    result = subprocess.run(
        ["git", "diff", "--name-status", f"{base_commit}..HEAD"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return [], ""

    output = result.stdout.strip()
    files = [_parse_name_status_line(line) for line in output.split("\n") if line.strip()]
    return files, output


def get_untracked_files_list() -> list[str]:
    """Get list of untracked files (excluding ignored).

    Returns:
        List of untracked file paths.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return []

    return [f for f in result.stdout.strip().split("\n") if f.strip()]


__all__ = [
    "DiffResult",
    "DirtyStateAction",
    "is_git_repo",
    "is_dirty",
    "has_untracked_files",
    "has_any_changes",
    "get_current_branch",
    "get_current_commit",
    "get_status_short",
    "branch_exists",
    "create_branch",
    "checkout_branch",
    "add_to_gitignore",
    "create_checkpoint_commit",
    "squash_commits",
    "handle_dirty_state",
    "stash_changes",
    "commit_changes",
    "get_diff_from_baseline",
    "get_changed_files_list",
    "get_untracked_files_list",
    "find_repo_root",
]
