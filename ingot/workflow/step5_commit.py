"""Step 5: Commit Changes - Automated Git Commit.

This module implements the fifth step of the workflow - showing a diff
summary, generating a commit message, letting the user customize it,
and executing the commit.

Philosophy: Automate the mundane. The user should review the diff summary,
tweak the commit message if needed, and confirm. Workflow artifacts
(specs/, .ingot/, .augment/) are excluded from staging.
"""

import subprocess
from dataclasses import dataclass

from ingot.integrations.backends.base import AIBackend
from ingot.integrations.git import has_any_changes
from ingot.ui.menus import CommitFailureChoice, show_commit_failure_menu
from ingot.ui.prompts import prompt_confirm, prompt_input
from ingot.utils.console import (
    console,
    print_header,
    print_info,
    print_success,
)
from ingot.workflow.git_utils import (
    get_working_tree_diff_from_baseline,
    is_workflow_artifact,
    parse_porcelain_z_output,
)
from ingot.workflow.state import WorkflowState


@dataclass
class Step5Result:
    """Result of Step 5 execution."""

    success: bool = True
    committed: bool = False
    commit_hash: str = ""
    commit_message: str = ""
    skipped_reason: str = ""
    error_message: str = ""
    files_staged: int = 0
    artifacts_excluded: int = 0


def _generate_commit_message(ticket_id: str, completed_tasks: list[str]) -> str:
    """Generate a commit message from ticket ID and completed tasks.

    Reuses the format from squash_commits() in git.py:
    - Single task: feat(TICKET): task name
    - Multiple: feat(TICKET): implement N tasks + body

    Args:
        ticket_id: The ticket identifier.
        completed_tasks: Non-empty list of completed task descriptions.
    """
    if len(completed_tasks) == 1:
        return f"feat({ticket_id}): {completed_tasks[0]}"

    task_list = "\n".join(f"- {t}" for t in completed_tasks)
    return (
        f"feat({ticket_id}): implement {len(completed_tasks)} tasks\n\n"
        f"Completed tasks:\n{task_list}"
    )


def _get_stageable_files() -> tuple[list[str], list[str]]:
    """Get files that can be staged, filtering out workflow artifacts.

    Uses ``git status --porcelain -z`` (NUL-delimited) so that filenames with
    spaces, tabs, and other special characters are handled correctly without
    needing to unescape C-style quoting.

    Returns:
        Tuple of (stageable_files, excluded_artifact_files).
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return [], []

    stageable: list[str] = []
    excluded: list[str] = []

    for _status, filepath in parse_porcelain_z_output(result.stdout):
        if is_workflow_artifact(filepath):
            excluded.append(filepath)
        else:
            stageable.append(filepath)

    return stageable, excluded


def _stage_files(files: list[str]) -> bool:
    """Stage specific files for commit.

    Uses 'git add -- <files>' (NOT git add -A) to stage only
    the specified files.
    """
    if not files:
        return False

    result = subprocess.run(
        ["git", "add", "--"] + files,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _show_diff_summary(state: WorkflowState) -> str:
    """Show a diff stat summary of changes.

    Uses baseline-anchored diff if available, falls back to simple git diff --stat,
    then to git status --short for untracked-only changes.
    """
    baseline = state.diff_baseline_ref

    if baseline:
        stat_output, git_error = get_working_tree_diff_from_baseline(baseline, stat_only=True)
        if not git_error and stat_output.strip():
            return stat_output

    # Fallback: simple git diff --stat (covers tracked file changes)
    result = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout

    # Fallback: git status --short (covers untracked-only changes)
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout

    return ""


def _execute_commit(message: str) -> tuple[bool, str]:
    """Execute git commit and return (success, commit_hash_or_error)."""
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "unknown error"
        return False, stderr

    # Get the commit hash
    hash_result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )

    commit_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ""
    return True, commit_hash


def step_5_commit(state: WorkflowState, backend: AIBackend | None = None) -> Step5Result:
    """Execute Step 5: Commit changes.

    Args:
        state: Current workflow state.
        backend: AI backend (reserved for future use, e.g. AI-generated messages).

    Flow:
    1. Check for any changes -- skip silently if clean
    2. Show diff stat summary
    3. Get stageable files, skip if only artifacts
    4. Generate commit message
    5. Let user edit subject line
    6. Confirm and commit
    7. On failure: show error and let user choose retry or skip
    """
    print_header("Step 5: Commit Changes")
    result = Step5Result()

    # 1. Check for changes
    if not has_any_changes():
        print_info("No changes to commit.")
        result.skipped_reason = "no_changes"
        return result

    # 2. Show diff summary
    diff_stat = _show_diff_summary(state)
    if diff_stat:
        console.print()
        print_info("Changes summary:")
        console.print(f"[dim]{diff_stat}[/dim]")

    # 3. Get stageable files
    stageable_files, excluded_files = _get_stageable_files()
    result.artifacts_excluded = len(excluded_files)

    if excluded_files:
        artifact_dirs = {p.split("/")[0] + "/" for p in excluded_files if "/" in p}
        artifact_files = {p for p in excluded_files if "/" not in p}
        artifact_names = sorted(artifact_dirs | artifact_files)
        print_info(
            f"Excluding {len(excluded_files)} workflow artifact(s): " f"{', '.join(artifact_names)}"
        )

    if not stageable_files:
        print_info("Only workflow artifacts changed. Nothing to commit.")
        result.skipped_reason = "artifacts_only"
        return result

    print_info(f"Files to stage: {len(stageable_files)}")

    # 4. Generate commit message (caller guarantees non-empty list)
    tasks = state.completed_tasks if state.completed_tasks else ["implement changes"]
    full_message = _generate_commit_message(state.ticket.id, tasks)

    # 5. Let user edit subject line
    subject_line = full_message.split("\n")[0]
    body = "\n".join(full_message.split("\n")[1:]).strip()

    console.print()
    edited_subject = prompt_input("Commit message subject", default=subject_line)

    # Reconstruct message with edited subject
    if body:
        commit_message = f"{edited_subject}\n\n{body}"
    else:
        commit_message = edited_subject

    result.commit_message = commit_message

    # 6. Confirm
    if not prompt_confirm("Commit changes?", default=True):
        print_info("Commit skipped by user.")
        result.skipped_reason = "user_declined"
        return result

    # 7. Stage and commit with interactive retry/skip on failure
    while True:
        # Stage files
        if not _stage_files(stageable_files):
            choice = show_commit_failure_menu("Failed to stage files")
            if choice == CommitFailureChoice.RETRY:
                continue
            print_info("Commit skipped by user after staging failure.")
            result.skipped_reason = "user_skipped"
            return result

        result.files_staged = len(stageable_files)

        # Commit
        success, commit_hash_or_error = _execute_commit(commit_message)
        if success:
            result.committed = True
            result.commit_hash = commit_hash_or_error
            print_success(f"Committed: {commit_hash_or_error} {edited_subject}")
            return result

        choice = show_commit_failure_menu(commit_hash_or_error)
        if choice == CommitFailureChoice.RETRY:
            continue

        print_info("Commit skipped by user.")
        result.skipped_reason = "user_skipped"
        result.error_message = f"Commit failed: {commit_hash_or_error}"
        return result


__all__ = [
    "step_5_commit",
    "Step5Result",
]
