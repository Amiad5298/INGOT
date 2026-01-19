"""Git operations for SPEC.

This module provides git-related functionality including branch management,
commit operations, dirty state handling, and checkpoint commit squashing.
"""

import subprocess
from enum import Enum
from pathlib import Path

from specflow.utils.console import print_error, print_info, print_success, print_warning
from specflow.utils.logging import log_command


class DirtyStateAction(Enum):
    """Actions for handling uncommitted changes."""

    STASH = "stash"
    COMMIT = "commit"
    DISCARD = "discard"
    CONTINUE = "continue"
    ABORT = "abort"


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
        True if there are uncommitted changes
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
        ticket_id: Jira ticket ID
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
        ticket_id: Jira ticket ID
        tasks: List of completed task names
    """
    if len(tasks) == 1:
        final_msg = f"feat({ticket_id}): {tasks[0]}"
    else:
        task_list = "\n".join(f"- {t}" for t in tasks)
        final_msg = f"feat({ticket_id}): implement {len(tasks)} tasks\n\nCompleted tasks:\n{task_list}"

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
    from specflow.ui.prompts import prompt_confirm, prompt_input

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


def has_changes() -> bool:
    """Check if there are any changes to commit.

    Returns:
        True if there are staged or unstaged changes
    """
    return is_dirty()


def revert_changes() -> None:
    """Revert all uncommitted changes."""
    subprocess.run(["git", "checkout", "."], capture_output=True)
    subprocess.run(["git", "clean", "-fd"], capture_output=True)


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


__all__ = [
    "DirtyStateAction",
    "is_git_repo",
    "is_dirty",
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
    "has_changes",
    "revert_changes",
    "stash_changes",
    "commit_changes",
]

