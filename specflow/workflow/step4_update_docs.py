"""Step 4: Update Documentation - Automated Doc Maintenance.

This module implements the fourth step of the workflow - automatically
updating documentation based on code changes made during the session.

Philosophy: Keep docs in sync with code. If code changed, docs should
reflect those changes before the user commits.

Non-Goal Enforcement: This step must NOT modify non-documentation files.
It snapshots non-doc files before the agent runs and reverts any non-doc
changes introduced by the agent.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from specflow.integrations.auggie import AuggieClient
from specflow.integrations.git import (
    DiffResult,
    get_diff_from_baseline,
    get_changed_files_list,
    get_untracked_files_list,
    has_any_changes,
)
from specflow.utils.console import print_error, print_header, print_info, print_success, print_warning
from specflow.workflow.state import WorkflowState


# Maximum diff size to avoid context overflow
MAX_DIFF_SIZE = 8000

# Documentation file patterns (extensions)
DOC_FILE_EXTENSIONS = frozenset({
    ".md",
    ".rst",
    ".txt",
    ".adoc",
    ".asciidoc",
})

# Documentation directory patterns (paths that contain docs)
DOC_PATH_PATTERNS = (
    "docs/",
    "doc/",
    "documentation/",
    "wiki/",
)

# Specific .github/ paths that ARE documentation (not workflows, actions, etc.)
GITHUB_DOC_PATTERNS = (
    ".github/readme",
    ".github/contributing",
    ".github/code_of_conduct",
    ".github/security",
    ".github/support",
    ".github/funding",
    ".github/issue_template",
    ".github/pull_request_template",
)

# .github/ paths that are NOT documentation (code/config)
GITHUB_NON_DOC_PATTERNS = (
    ".github/workflows/",
    ".github/actions/",
    ".github/scripts/",
)

# Files that are always considered documentation
DOC_FILE_NAMES = frozenset({
    "README",
    "CHANGELOG",
    "CONTRIBUTING",
    "LICENSE",
    "AUTHORS",
    "HISTORY",
    "NEWS",
    "RELEASE",
    "CHANGES",
})


def is_doc_file(filepath: str) -> bool:
    """Check if a file is a documentation file.

    Args:
        filepath: Path to the file (relative or absolute)

    Returns:
        True if the file is a documentation file
    """
    path = Path(filepath)
    filepath_lower = filepath.lower().replace("\\", "/")

    # Check by extension first
    if path.suffix.lower() in DOC_FILE_EXTENSIONS:
        # Even with doc extension, exclude .github/workflows/*.md etc.
        for non_doc_pattern in GITHUB_NON_DOC_PATTERNS:
            if non_doc_pattern in filepath_lower:
                return False
        return True

    # Check if in a standard docs directory
    for pattern in DOC_PATH_PATTERNS:
        if pattern in filepath_lower:
            return True

    # Special handling for .github/ - only allow specific doc patterns
    if ".github/" in filepath_lower:
        # Check if it's explicitly a non-doc path
        for non_doc_pattern in GITHUB_NON_DOC_PATTERNS:
            if non_doc_pattern in filepath_lower:
                return False
        # Check if it matches a known doc pattern
        for doc_pattern in GITHUB_DOC_PATTERNS:
            if doc_pattern in filepath_lower:
                return True
        # Default: files directly in .github/ with doc names might be docs
        # but don't treat arbitrary .github files as docs

    # Check by filename (without extension)
    stem = path.stem.upper()
    if stem in DOC_FILE_NAMES:
        return True

    return False


@dataclass
class FileSnapshot:
    """Snapshot of a file's state for restoration.

    Attributes:
        path: File path relative to repo root.
        was_untracked: True if file was untracked (status code '??') at snapshot time.
        was_dirty: True if file had pre-agent modifications (tracked but modified).
        content: Byte content if file existed and was dirty pre-agent.
    """

    path: str
    was_untracked: bool = False
    was_dirty: bool = False
    content: Optional[bytes] = None

    @classmethod
    def capture(cls, filepath: str, status_code: str) -> "FileSnapshot":
        """Capture the current state of a file based on git status code.

        Args:
            filepath: Path to the file.
            status_code: Two-character git status code (e.g., '??', 'M ', ' M', 'MM').

        Returns:
            FileSnapshot with appropriate state captured.
        """
        is_untracked = status_code == "??"
        # File is dirty if it has any tracked modification (not untracked)
        is_dirty = not is_untracked and status_code.strip() != ""

        content = None
        if is_dirty:
            # Only capture content for files that were already dirty pre-agent
            # so we can restore them to their pre-agent dirty state
            path = Path(filepath)
            if path.exists() and path.is_file():
                try:
                    content = path.read_bytes()
                except (OSError, IOError):
                    pass

        return cls(
            path=filepath,
            was_untracked=is_untracked,
            was_dirty=is_dirty,
            content=content,
        )


def _git_restore_file(filepath: str) -> bool:
    """Restore a tracked file using git restore.

    Uses 'git restore --worktree --staged -- <file>' to fully restore
    a tracked file to its committed state.

    Args:
        filepath: Path to the file to restore.

    Returns:
        True if restoration succeeded.
    """
    result = subprocess.run(
        ["git", "restore", "--worktree", "--staged", "--", filepath],
        capture_output=True,
    )
    return result.returncode == 0


@dataclass
class NonDocSnapshot:
    """Snapshot of all non-doc files for enforcement.

    This class tracks the pre-agent state of non-documentation files so that
    any changes made by the doc-updater agent can be detected and reverted.

    Key behaviors:
    - For untracked files ('??'): No content captured; revert by deleting.
    - For tracked dirty files: Content captured; revert by writing back content.
    - For tracked clean files that become dirty: Use git restore to revert.
    """

    snapshots: dict[str, FileSnapshot] = field(default_factory=dict)

    @classmethod
    def capture_non_doc_state(cls) -> "NonDocSnapshot":
        """Capture state of all non-doc files with changes (tracked or untracked)."""
        snapshot = cls()

        # Use git status --porcelain for parseable output
        # Format: XY filename (where XY is 2-char status code)
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return snapshot

        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue

            # Parse porcelain format: XY filename
            # X = index status, Y = worktree status
            status_code = line[:2]
            filepath = line[3:].strip()

            # Handle renamed files (format: old -> new)
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1]

            # Skip doc files - we only want to track non-doc files
            if is_doc_file(filepath):
                continue

            snapshot.snapshots[filepath] = FileSnapshot.capture(filepath, status_code)

        return snapshot

    def detect_changes(self) -> list[str]:
        """Detect which non-doc files have changed since snapshot.

        This detects:
        1. Pre-dirty files that were modified further.
        2. Previously clean tracked files that are now dirty.
        3. New untracked files created by the agent.

        Returns:
            List of file paths that were modified.
        """
        changed = []

        # Check existing pre-dirty snapshots for further modifications
        for filepath, old_snapshot in self.snapshots.items():
            if old_snapshot.was_dirty and old_snapshot.content is not None:
                # Compare content to detect changes to pre-dirty files
                path = Path(filepath)
                if path.exists() and path.is_file():
                    try:
                        current_content = path.read_bytes()
                        if current_content != old_snapshot.content:
                            changed.append(filepath)
                    except (OSError, IOError):
                        # Can't read file - assume changed
                        changed.append(filepath)
                else:
                    # File was deleted
                    changed.append(filepath)

        # Get current git status to detect new changes
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                status_code = line[:2]
                filepath = line[3:].strip()
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[-1]

                # Skip doc files
                if is_doc_file(filepath):
                    continue

                if filepath not in self.snapshots:
                    # File not in our snapshot - agent created/modified it
                    is_untracked = status_code == "??"
                    # Record it for revert handling
                    self.snapshots[filepath] = FileSnapshot(
                        path=filepath,
                        was_untracked=is_untracked,
                        was_dirty=False,  # It wasn't dirty before agent ran
                        content=None,
                    )
                    changed.append(filepath)

        return list(set(changed))

    def revert_changes(self, filepaths: list[str]) -> list[str]:
        """Revert specified files to their snapshot state.

        Revert strategy:
        - Pre-dirty files: Restore saved content.
        - Pre-untracked files: Delete them (agent shouldn't modify untracked).
        - Previously clean tracked files: Use git restore.

        Args:
            filepaths: List of files to revert.

        Returns:
            List of files that were successfully reverted.
        """
        reverted = []
        for filepath in filepaths:
            snapshot = self.snapshots.get(filepath)

            if snapshot is None:
                # No snapshot - shouldn't happen, but try git restore
                if _git_restore_file(filepath):
                    reverted.append(filepath)
                continue

            if snapshot.was_dirty and snapshot.content is not None:
                # Restore to pre-agent dirty state by writing back content
                try:
                    path = Path(filepath)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(snapshot.content)
                    reverted.append(filepath)
                except (OSError, IOError):
                    pass
            elif snapshot.was_untracked:
                # File was untracked pre-agent - delete it if it exists
                try:
                    path = Path(filepath)
                    if path.exists():
                        path.unlink()
                        reverted.append(filepath)
                except (OSError, IOError):
                    pass
            else:
                # File was tracked and clean pre-agent - use git restore
                if _git_restore_file(filepath):
                    reverted.append(filepath)

        return reverted


@dataclass
class Step4Result:
    """Result of Step 4 execution.

    Attributes:
        success: True if step completed without critical errors
        docs_updated: True if documentation was updated
        agent_ran: True if the doc-updater agent was invoked
        non_doc_reverted: List of non-doc files that were reverted
        non_doc_revert_failed: List of non-doc files that failed to revert
        had_violations: True if agent violated doc-only constraint
        error_message: Error description if success is False
    """

    success: bool = True
    docs_updated: bool = False
    agent_ran: bool = False
    non_doc_reverted: list[str] = field(default_factory=list)
    non_doc_revert_failed: list[str] = field(default_factory=list)
    had_violations: bool = False
    error_message: str = ""


class AuggieClientProtocol(Protocol):
    """Protocol for AuggieClient to allow dependency injection."""

    def run_print_with_output(
        self,
        prompt: str,
        *,
        agent: str,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        ...


def step_4_update_docs(
    state: WorkflowState,
    *,
    auggie_client: Optional[AuggieClientProtocol] = None,
) -> Step4Result:
    """Execute Step 4: Update documentation based on code changes.

    This step:
    1. Checks if there are any changes to analyze
    2. Snapshots non-doc file state for enforcement
    3. Gets the git diff from the baseline commit
    4. Invokes the spec-doc-updater agent to analyze and update docs
    5. Detects and reverts any non-doc changes made by the agent
    6. Reports what documentation was updated

    This step is NON-BLOCKING: errors will be reported but won't fail the workflow.

    Args:
        state: Current workflow state
        auggie_client: Optional client for dependency injection in tests

    Returns:
        Step4Result with details of what happened (always succeeds for workflow)
    """
    print_header("Step 4: Update Documentation")
    result = Step4Result()

    # Check if there are any changes to analyze (including untracked files)
    if not has_any_changes() and not state.base_commit:
        print_info("No changes detected. Skipping documentation update.")
        return result

    # Get diff from baseline (now returns DiffResult)
    # Note: get_diff_from_baseline handles missing base_commit gracefully
    # by falling back to staged + unstaged + untracked changes
    diff_result = get_diff_from_baseline(state.base_commit)

    if diff_result.has_error:
        print_warning(f"Failed to compute diff; skipping documentation update: {diff_result.error_message}")
        result.error_message = diff_result.error_message
        # Non-blocking - still return success for workflow
        return result

    if not diff_result.has_changes:
        print_info("No code changes to document. Skipping.")
        return result

    print_info("Analyzing code changes for documentation updates...")

    # Snapshot non-doc files BEFORE agent runs (for enforcement)
    non_doc_snapshot = NonDocSnapshot.capture_non_doc_state()

    # Build prompt for doc-updater agent
    prompt = _build_doc_update_prompt(state, diff_result)

    # Use provided client or create default
    client = auggie_client or AuggieClient()

    try:
        result.agent_ran = True
        success, output = client.run_print_with_output(
            prompt,
            agent=state.subagent_names.get("doc_updater", "spec-doc-updater"),
            dont_save_session=True,
        )

        # Enforce doc-only changes: detect and revert non-doc modifications
        non_doc_changes = non_doc_snapshot.detect_changes()
        if non_doc_changes:
            result.had_violations = True

            # Make violations highly visible with prominent banner
            print_error("=" * 60)
            print_error("⛔ GUARDRAIL VIOLATION: NON-DOCUMENTATION FILES MODIFIED ⛔")
            print_error("=" * 60)
            print_warning(
                f"The doc-updater agent modified {len(non_doc_changes)} non-documentation file(s)."
            )
            print_warning("These changes violate the doc-only constraint and will be reverted:")
            for filepath in non_doc_changes:
                print_warning(f"  • {filepath}")

            # Attempt to revert all non-doc changes
            reverted = non_doc_snapshot.revert_changes(non_doc_changes)
            result.non_doc_reverted = reverted

            if len(reverted) == len(non_doc_changes):
                print_info(f"✓ Successfully reverted all {len(reverted)} non-doc file(s)")
            else:
                failed = list(set(non_doc_changes) - set(reverted))
                result.non_doc_revert_failed = failed
                print_error(f"⚠️  CRITICAL: Failed to revert {len(failed)} file(s):")
                for filepath in failed:
                    print_error(f"    ✗ {filepath}")
                print_error("Manual review required for these files!")

            print_error("=" * 60)

        if success:
            result.docs_updated = True
            if result.had_violations:
                print_warning("Documentation update completed with violations (see above)")
            else:
                print_success("Documentation update completed successfully")
        else:
            print_warning("Documentation update reported issues (non-blocking)")

        return result

    except Exception as e:
        print_error(f"Documentation update failed with exception: {e}")
        result.error_message = str(e)
        # Non-blocking - still return success for workflow
        return result


def _build_doc_update_prompt(state: WorkflowState, diff_result: DiffResult) -> str:
    """Build the prompt for the doc-updater agent.

    Args:
        state: Current workflow state
        diff_result: DiffResult from get_diff_from_baseline

    Returns:
        Formatted prompt string with clear sections and strong doc-only instruction
    """
    # Build changed files summary (always include, won't be truncated)
    changed_files_section = ""
    if diff_result.changed_files:
        changed_files_section = "## Changed Files\n```\n"
        for f in diff_result.changed_files[:50]:  # Limit to 50 files
            changed_files_section += f"  {f}\n"
        if len(diff_result.changed_files) > 50:
            changed_files_section += f"  ... and {len(diff_result.changed_files) - 50} more files\n"
        changed_files_section += "```\n\n"

    # Build diffstat summary (always include)
    diffstat_section = ""
    if diff_result.diffstat:
        diffstat_section = f"## Change Statistics\n```\n{diff_result.diffstat}\n```\n\n"

    # Build untracked files list
    untracked_section = ""
    if diff_result.untracked_files:
        untracked_section = "## New (Untracked) Files\n```\n"
        for f in diff_result.untracked_files[:30]:
            untracked_section += f"  {f}\n"
        if len(diff_result.untracked_files) > 30:
            untracked_section += f"  ... and {len(diff_result.untracked_files) - 30} more\n"
        untracked_section += "```\n\n"

    # Truncate full diff to avoid context overflow
    diff_content = diff_result.diff
    truncated_diff = diff_content[:MAX_DIFF_SIZE]
    truncation_note = ""
    if len(diff_content) > MAX_DIFF_SIZE:
        truncation_note = "\n\n... (diff truncated due to size - see Changed Files and Statistics above for full scope)"

    return f"""Update documentation for: {state.ticket.ticket_id}

## ⛔️ CRITICAL RESTRICTION ⛔️

**YOU MUST ONLY EDIT DOCUMENTATION FILES.**

Documentation files include:
- Files with extensions: .md, .rst, .txt, .adoc
- Files in directories: docs/, doc/, documentation/, .github/
- Files named: README, CHANGELOG, CONTRIBUTING, LICENSE, AUTHORS, etc.

**DO NOT EDIT:**
- Source code files (.py, .js, .ts, .go, .java, .rs, etc.)
- Configuration files (.json, .yaml, .toml, .ini, etc.)
- Test files
- Any other non-documentation files

Any changes to non-documentation files will be automatically reverted.

{changed_files_section}{diffstat_section}{untracked_section}## Code Changes (git diff)
```diff
{truncated_diff}{truncation_note}
```

## Task Summary
Review the code changes made in this workflow session and update any
documentation files that need to reflect these changes.

## Instructions
1. Analyze what functionality was added or changed
2. Identify which documentation files need updates (ONLY .md, .rst, etc.)
3. Make targeted updates to keep docs in sync with code
4. Report what was updated

Focus on README.md, API docs, and any relevant documentation files.
Do NOT update docs for unchanged code.
Do NOT create new documentation files unless explicitly needed."""


__all__ = [
    "step_4_update_docs",
    "Step4Result",
    "is_doc_file",
    "DOC_FILE_EXTENSIONS",
    "DOC_PATH_PATTERNS",
]

