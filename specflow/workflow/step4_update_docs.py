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
    ".github/",
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

    # Check by extension
    if path.suffix.lower() in DOC_FILE_EXTENSIONS:
        return True

    # Check if in a docs directory
    filepath_lower = filepath.lower().replace("\\", "/")
    for pattern in DOC_PATH_PATTERNS:
        if pattern in filepath_lower:
            return True

    # Check by filename (without extension)
    stem = path.stem.upper()
    if stem in DOC_FILE_NAMES:
        return True

    return False


@dataclass
class FileSnapshot:
    """Snapshot of a file's state for restoration."""

    path: str
    existed: bool
    content: Optional[bytes] = None

    @classmethod
    def capture(cls, filepath: str) -> "FileSnapshot":
        """Capture the current state of a file."""
        path = Path(filepath)
        if path.exists() and path.is_file():
            try:
                content = path.read_bytes()
                return cls(path=filepath, existed=True, content=content)
            except (OSError, IOError):
                return cls(path=filepath, existed=True, content=None)
        return cls(path=filepath, existed=False, content=None)

    def restore(self) -> bool:
        """Restore file to its captured state.

        Returns:
            True if restoration was performed
        """
        path = Path(self.path)
        if self.existed and self.content is not None:
            # Restore original content
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(self.content)
                return True
            except (OSError, IOError):
                return False
        elif not self.existed:
            # File didn't exist before, remove it
            try:
                if path.exists():
                    path.unlink()
                return True
            except (OSError, IOError):
                return False
        return False


@dataclass
class NonDocSnapshot:
    """Snapshot of all non-doc files for enforcement."""

    snapshots: dict[str, FileSnapshot] = field(default_factory=dict)

    @classmethod
    def capture_non_doc_state(cls) -> "NonDocSnapshot":
        """Capture state of all non-doc tracked and modified files."""
        snapshot = cls()

        # Get all tracked files that are modified
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
            status = line[:2]
            filepath = line[3:].strip()

            # Handle renamed files (format: old -> new)
            if " -> " in filepath:
                filepath = filepath.split(" -> ")[-1]

            # Skip doc files - we only want to track non-doc files
            if is_doc_file(filepath):
                continue

            snapshot.snapshots[filepath] = FileSnapshot.capture(filepath)

        return snapshot

    def detect_changes(self) -> list[str]:
        """Detect which non-doc files have changed since snapshot.

        Returns:
            List of file paths that were modified
        """
        changed = []

        # Check existing snapshots for modifications
        for filepath, old_snapshot in self.snapshots.items():
            current = FileSnapshot.capture(filepath)

            if old_snapshot.existed != current.existed:
                changed.append(filepath)
            elif old_snapshot.content != current.content:
                changed.append(filepath)

        # Check for new non-doc files
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue

                filepath = line[3:].strip()
                if " -> " in filepath:
                    filepath = filepath.split(" -> ")[-1]

                if not is_doc_file(filepath) and filepath not in self.snapshots:
                    # New non-doc file created by agent
                    changed.append(filepath)
                    self.snapshots[filepath] = FileSnapshot(
                        path=filepath, existed=False
                    )

        return list(set(changed))

    def revert_changes(self, filepaths: list[str]) -> list[str]:
        """Revert specified files to their snapshot state.

        Args:
            filepaths: List of files to revert

        Returns:
            List of files that were successfully reverted
        """
        reverted = []
        for filepath in filepaths:
            if filepath in self.snapshots:
                if self.snapshots[filepath].restore():
                    reverted.append(filepath)
            else:
                # File was created and doesn't have a snapshot - delete it
                path = Path(filepath)
                try:
                    if path.exists():
                        path.unlink()
                        reverted.append(filepath)
                except (OSError, IOError):
                    pass
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

