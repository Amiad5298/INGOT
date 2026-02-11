"""Step 4: Update Documentation - Automated Doc Maintenance.

This module implements the fourth step of the workflow - automatically
updating documentation based on code changes made during the session.

Philosophy: Keep docs in sync with code. If code changed, docs should
reflect those changes before the user commits.

Non-Goal Enforcement: This step must NOT modify non-documentation files.
It snapshots non-doc files before the agent runs and reverts any non-doc
changes introduced by the agent.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ingot.integrations.backends.base import AIBackend
from ingot.integrations.git import (
    DiffResult,
    get_diff_from_baseline,
    has_any_changes,
)
from ingot.utils.console import (
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)
from ingot.workflow.state import WorkflowState

# Maximum diff size to avoid context overflow
MAX_DIFF_SIZE = 8000

# Log directory names for workflow steps
LOG_DIR_DOC_UPDATE = "doc_update"

# Documentation file patterns (extensions)
# Note: .txt is intentionally excluded to avoid modifying config files like
# requirements.txt, constraints.txt, etc.
DOC_FILE_EXTENSIONS = frozenset(
    {
        ".md",
        ".rst",
        ".adoc",
        ".asciidoc",
    }
)

# Documentation directory patterns (paths that contain docs)
DOC_PATH_PATTERNS = (
    "docs/",
    "doc/",
    "documentation/",
    "wiki/",
)

# Specific .github/ directory/file names that ARE documentation (case-insensitive)
# These are checked as exact path segments after .github/
GITHUB_DOC_NAMES = frozenset(
    {
        "readme",
        "contributing",
        "code_of_conduct",
        "security",
        "support",
        "funding",
        "issue_template",
        "pull_request_template",
    }
)

# .github/ subdirectories that are NOT documentation (code/config)
# These are checked as directory names that must NOT be in the path
GITHUB_NON_DOC_DIRS = frozenset(
    {
        "workflows",
        "actions",
        "scripts",
    }
)

# Legacy patterns for backward compatibility (used for substring checks)
GITHUB_NON_DOC_PATTERNS = (
    ".github/workflows/",
    ".github/actions/",
    ".github/scripts/",
)

# Files that are always considered documentation
DOC_FILE_NAMES = frozenset(
    {
        "README",
        "CHANGELOG",
        "CONTRIBUTING",
        "LICENSE",
        "AUTHORS",
        "HISTORY",
        "NEWS",
        "RELEASE",
        "CHANGES",
    }
)


def _is_github_doc_path(filepath_lower: str) -> bool:
    """Check if a .github/ path is a documentation path using segment-aware matching.

    This prevents false positives like .github/readme-scripts/tool.py being
    classified as documentation due to substring matching on "readme".
    """
    # Split path into segments
    parts = filepath_lower.split("/")

    # Find .github in the path
    try:
        github_idx = parts.index(".github")
    except ValueError:
        return False

    # Check if any segment after .github is a non-doc directory
    for part in parts[github_idx + 1 :]:
        if part in GITHUB_NON_DOC_DIRS:
            return False

    # Check if the first segment after .github is a doc name
    if github_idx + 1 < len(parts):
        next_segment = parts[github_idx + 1]
        # Remove extension if present for comparison
        segment_stem = next_segment.rsplit(".", 1)[0] if "." in next_segment else next_segment
        if segment_stem in GITHUB_DOC_NAMES:
            return True

    return False


def is_doc_file(filepath: str) -> bool:
    """Check if a file is a documentation file."""
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

    # Special handling for .github/ - use segment-aware matching
    if ".github/" in filepath_lower:
        return _is_github_doc_path(filepath_lower)

    # Check by filename (without extension)
    stem = path.stem.upper()
    if stem in DOC_FILE_NAMES:
        return True

    return False


@dataclass
class FileSnapshot:
    """Snapshot of a file's state for restoration."""

    path: str
    was_untracked: bool = False
    was_dirty: bool = False
    existed: bool = True
    content: bytes | None = None

    @classmethod
    def capture(cls, filepath: str, status_code: str) -> "FileSnapshot":
        """Capture the current state of a file based on git status code."""
        is_untracked = status_code == "??"
        # File is dirty if it has any tracked modification (not untracked)
        is_dirty = not is_untracked and status_code.strip() != ""

        path = Path(filepath)
        file_exists = path.exists() and path.is_file()
        content = None

        # Capture content for files that exist (both dirty and untracked)
        # so we can restore them to their pre-agent state
        if file_exists:
            try:
                content = path.read_bytes()
            except OSError:
                pass

        return cls(
            path=filepath,
            was_untracked=is_untracked,
            was_dirty=is_dirty,
            existed=file_exists,
            content=content,
        )


def _git_restore_file(filepath: str) -> bool:
    """Restore a tracked file using git restore.

    Uses 'git restore --worktree --staged -- <file>' to fully restore
    a tracked file to its committed state.
    """
    result = subprocess.run(
        ["git", "restore", "--worktree", "--staged", "--", filepath],
        capture_output=True,
    )
    return result.returncode == 0


def _parse_porcelain_z_output(output: str) -> list[tuple[str, str]]:
    """Parse git status --porcelain -z output.

    The -z flag uses NUL as delimiter between entries and between renamed file paths.
    This handles filenames with spaces and special characters correctly.

    Format for each entry:
    - Regular file: "XY path\\0" (status code followed by space, then path, then NUL)
    - Renamed file: "XY old_path\\0new_path\\0" (status, old path, NUL, new path, NUL)
    """
    if not output:
        return []

    entries = []
    # Split on NUL bytes
    parts = output.split("\0")

    i = 0
    while i < len(parts):
        part = parts[i]
        if not part:
            i += 1
            continue

        # Status code is first 2 chars, then a space, then the path
        if len(part) < 3:
            i += 1
            continue

        status_code = part[:2]
        filepath = part[3:]

        # Check if this is a rename (R) or copy (C) - next part is the destination
        if status_code[0] in ("R", "C") and i + 1 < len(parts) and parts[i + 1]:
            # For renames/copies, the current filepath is the old path
            # The next part (before next status entry) is the new path
            new_path = parts[i + 1]
            entries.append((status_code, new_path))
            i += 2  # Skip both old path entry and new path
        else:
            entries.append((status_code, filepath))
            i += 1

    return entries


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

        # Use git status --porcelain -z for robust parsing
        # The -z flag uses NUL as delimiter, handling filenames with spaces correctly
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "-uall"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return snapshot

        # Parse the null-delimited output
        for status_code, filepath in _parse_porcelain_z_output(result.stdout):
            # Skip doc files - we only want to track non-doc files
            if is_doc_file(filepath):
                continue

            snapshot.snapshots[filepath] = FileSnapshot.capture(filepath, status_code)

        return snapshot

    def detect_changes(self) -> list[str]:
        """Detect which non-doc files have changed since snapshot.

        This detects:
        1. Pre-existing files (dirty or untracked) that were modified.
        2. Pre-existing files that were deleted by agent.
        3. Previously non-existent files that now exist (agent recreated them).
        4. Previously clean tracked files that are now dirty.
        5. New untracked files created by the agent.
        """
        changed = []

        # Check ALL existing snapshots for changes (not just was_dirty)
        for filepath, old_snapshot in self.snapshots.items():
            path = Path(filepath)
            file_exists_now = path.exists() and path.is_file()

            # Case 1: File didn't exist pre-Step4 but exists now (agent created it)
            # This handles tracked files that were deleted before Step 4 and recreated
            if not old_snapshot.existed and file_exists_now:
                changed.append(filepath)
                continue

            # Case 2: File existed pre-Step4 but is missing now (agent deleted it)
            if old_snapshot.existed and not file_exists_now:
                changed.append(filepath)
                continue

            # Case 3: File has captured content - compare to current content
            # This works for both pre-dirty tracked files AND pre-existing untracked files
            if old_snapshot.content is not None:
                if file_exists_now:
                    try:
                        current_content = path.read_bytes()
                        if current_content != old_snapshot.content:
                            changed.append(filepath)
                    except OSError:
                        # Can't read file - assume changed
                        changed.append(filepath)
                # Note: file missing case already handled above

        # Get current git status to detect NEW changes (files not in original snapshot)
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "-uall"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            for status_code, filepath in _parse_porcelain_z_output(result.stdout):
                # Skip doc files
                if is_doc_file(filepath):
                    continue

                if filepath not in self.snapshots:
                    # File not in our snapshot - agent created/modified it
                    is_untracked = status_code == "??"
                    # Record it for revert handling
                    # CRITICAL: For tracked files that were CLEAN before Step 4 (not in
                    # snapshot), we set existed=True so revert_changes() uses git restore.
                    # For truly untracked files ("??"), set existed=False so they get deleted.
                    # This prevents deleting tracked files that the agent modified.
                    file_existed_pre_step4 = (
                        not is_untracked
                    )  # Tracked files "existed" for restore purposes
                    self.snapshots[filepath] = FileSnapshot(
                        path=filepath,
                        was_untracked=is_untracked,
                        was_dirty=False,  # It wasn't dirty before agent ran
                        existed=file_existed_pre_step4,
                        content=None,
                    )
                    changed.append(filepath)

        return list(set(changed))

    def revert_changes(self, filepaths: list[str]) -> list[str]:
        """Revert specified files to their snapshot state.

        Revert strategy:
        - Pre-dirty files with content: Restore saved content.
        - Pre-untracked files with content: Restore saved content.
        - Files that didn't exist pre-Step4 (new or recreated): Delete them.
        - Previously clean tracked files that existed: Use git restore.
        - Deleted files with saved content: Restore the content.
        """
        reverted = []
        for filepath in filepaths:
            snapshot = self.snapshots.get(filepath)

            if snapshot is None:
                # No snapshot - file was created by agent, try git restore or delete
                path = Path(filepath)
                if _git_restore_file(filepath):
                    reverted.append(filepath)
                elif path.exists():
                    # If git restore fails, it might be a new untracked file - delete it
                    try:
                        path.unlink()
                        reverted.append(filepath)
                    except OSError:
                        pass
                continue

            # If we have saved content, always restore it (works for dirty, untracked, deleted)
            if snapshot.content is not None:
                try:
                    path = Path(filepath)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(snapshot.content)
                    reverted.append(filepath)
                except OSError:
                    pass
            elif not snapshot.existed:
                # A1/A3 FIX: File did NOT exist pre-Step4 (either new untracked or
                # previously-deleted tracked file that agent recreated) - delete it
                # DO NOT call git restore here - that would resurrect the file from HEAD!
                try:
                    path = Path(filepath)
                    if path.exists():
                        path.unlink()
                        reverted.append(filepath)
                    else:
                        # File already doesn't exist - consider it reverted
                        reverted.append(filepath)
                except OSError:
                    pass
            elif not snapshot.was_untracked:
                # File was tracked, existed pre-Step4, and was clean - use git restore
                if _git_restore_file(filepath):
                    reverted.append(filepath)
            # else: untracked file existed but we failed to capture content - can't restore

        return reverted


@dataclass
class Step4Result:
    """Result of Step 4 execution."""

    success: bool = True
    docs_updated: bool = False
    agent_ran: bool = False
    non_doc_reverted: list[str] = field(default_factory=list)
    non_doc_revert_failed: list[str] = field(default_factory=list)
    had_violations: bool = False
    error_message: str = ""


def step_4_update_docs(
    state: WorkflowState,
    *,
    backend: AIBackend,
) -> Step4Result:
    """Execute Step 4: Update documentation based on code changes.

    This step:
    1. Checks if there are any changes to analyze
    2. Snapshots non-doc file state for enforcement
    3. Gets the git diff from the baseline commit
    4. Invokes the ingot-doc-updater agent to analyze and update docs
    5. Detects and reverts any non-doc changes made by the agent
    6. Reports what documentation was updated

    This step is NON-BLOCKING: errors will be reported but won't fail the workflow.

    Uses TaskRunnerUI in single-operation mode to provide a consistent
    collapsible UI with verbose toggle, matching the UX of Steps 1 and 3.
    """
    from ingot.ui.tui import TaskRunnerUI
    from ingot.workflow.events import format_run_directory
    from ingot.workflow.log_management import get_log_base_dir

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
        print_warning(
            f"Failed to compute diff; skipping documentation update: {diff_result.error_message}"
        )
        result.error_message = diff_result.error_message
        # Non-blocking - still return success for workflow
        return result

    if not diff_result.has_changes:
        print_info("No code changes to document. Skipping.")
        return result

    # Snapshot non-doc files BEFORE agent runs (for enforcement)
    non_doc_snapshot = NonDocSnapshot.capture_non_doc_state()

    # Build prompt for doc-updater agent
    prompt = _build_doc_update_prompt(state, diff_result)

    # Create log directory for documentation update (use safe_filename_stem for paths)
    log_dir = get_log_base_dir() / state.ticket.safe_filename_stem / LOG_DIR_DOC_UPDATE
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{format_run_directory()}.log"

    # Create UI with collapsible panel and verbose toggle (single-operation mode)
    ui = TaskRunnerUI(
        status_message="Updating documentation...",
        ticket_id=state.ticket.id,  # Keep original ID for display
        single_operation_mode=True,
    )
    ui.set_log_path(log_path)

    try:
        result.agent_ran = True

        with ui:
            success, output = backend.run_with_callback(
                prompt,
                subagent=state.subagent_names.get("doc_updater", "ingot-doc-updater"),
                output_callback=ui.handle_output_line,
                dont_save_session=True,
            )

            # Check if user requested quit
            if ui.check_quit_requested():
                print_warning("Documentation update cancelled by user.")
                return result

        ui.print_summary(success)

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
    """Build the prompt for the doc-updater agent."""
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
    diff_was_truncated = len(diff_content) > MAX_DIFF_SIZE
    if diff_was_truncated:
        cut = diff_content[:MAX_DIFF_SIZE].rfind("\n")
        if cut <= 0:
            cut = MAX_DIFF_SIZE
        truncated_diff = diff_content[:cut]
        truncation_note = "\n\n... (diff truncated due to size - see Changed Files and Statistics above for full scope)"
    else:
        truncated_diff = diff_content
        truncation_note = ""

    # Only include changed files list and diffstat when diff is truncated
    # (they're redundant when the full diff is present)
    context_sections = ""
    if diff_was_truncated:
        context_sections = f"{changed_files_section}{diffstat_section}"
    # Always include untracked files (they're not in diffs)
    context_sections += untracked_section

    return f"""Update documentation for: {state.ticket.id}

## ⛔️ CRITICAL RESTRICTION ⛔️

**YOU MUST ONLY EDIT DOCUMENTATION FILES.**

Documentation files include:
- Files with extensions: .md, .rst, .adoc, .asciidoc
- Files in directories: docs/, doc/, documentation/
- .github/ doc files: README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, ISSUE_TEMPLATE, PULL_REQUEST_TEMPLATE
- Root files named: README, CHANGELOG, CONTRIBUTING, LICENSE, AUTHORS, etc.

**DO NOT EDIT:**
- Source code files (.py, .js, .ts, .go, .java, .rs, etc.)
- Configuration files (.json, .yaml, .toml, .ini, .txt, requirements.txt, constraints.txt, etc.)
- Test files
- .github/workflows/, .github/actions/, .github/scripts/ (these are code, not docs)
- Any other non-documentation files

Any changes to non-documentation files will be automatically reverted.

{context_sections}## Code Changes (git diff)
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
    "LOG_DIR_DOC_UPDATE",
]
