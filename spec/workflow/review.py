"""Code review utilities for Step 3 execution.

This module provides utilities for running code reviews during the
execution phase, including parsing review output, building review
prompts, and coordinating the review workflow with optional auto-fix.

Supports baseline-anchored diffs to ensure reviews only inspect changes
introduced by the current workflow, not pre-existing dirty changes.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from spec.integrations.auggie import AuggieClient
from spec.ui.prompts import prompt_confirm
from spec.utils.console import (
    print_info,
    print_step,
    print_success,
    print_warning,
)
from spec.workflow.git_utils import get_smart_diff, get_smart_diff_from_baseline

if TYPE_CHECKING:
    from spec.workflow.state import WorkflowState


class ReviewStatus(Enum):
    """Status codes returned by the review parser."""

    PASS = "PASS"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


def parse_review_status(output: str) -> ReviewStatus:
    """Parse review status from agent output.

    Extracts the final status marker from review output. The canonical format is:
        **Status**: PASS
        **Status**: NEEDS_ATTENTION

    This parser is robust to multiple formats:
    - Canonical: **Status**: PASS or Status: PASS
    - Bullet form: - **PASS** - description or - **NEEDS_ATTENTION** - description
    - Standalone: **PASS** or NEEDS_ATTENTION on its own line near the end
    - Case variations (PASS, Pass, pass)
    - Multiple occurrences (uses last one as final verdict)
    - PASS in normal prose is NOT matched (avoids false positives)

    Args:
        output: Review agent output text

    Returns:
        ReviewStatus.PASS if review passed, ReviewStatus.NEEDS_ATTENTION if
        issues found, or ReviewStatus.NEEDS_ATTENTION if status cannot be
        determined (fail-safe)

    Examples:
        >>> parse_review_status("**Status**: PASS\\n\\nLooks good!")
        <ReviewStatus.PASS: 'PASS'>
        >>> parse_review_status("Status: NEEDS_ATTENTION\\n\\nIssues found")
        <ReviewStatus.NEEDS_ATTENTION: 'NEEDS_ATTENTION'>
        >>> parse_review_status("- **PASS** - Changes look good")
        <ReviewStatus.PASS: 'PASS'>
        >>> parse_review_status("Ambiguous output")
        <ReviewStatus.NEEDS_ATTENTION: 'NEEDS_ATTENTION'>
    """
    if not output or not output.strip():
        return ReviewStatus.NEEDS_ATTENTION

    # All status patterns we recognize, ordered by specificity
    # Each pattern captures the status keyword (PASS or NEEDS_ATTENTION)
    patterns = [
        # 1. Canonical format: **Status**: PASS or Status: PASS
        r'(?:\*\*)?Status(?:\*\*)?\s*:\s*(PASS|NEEDS_ATTENTION)',
        # 2. Bullet format: - **PASS** - ... or - **NEEDS_ATTENTION** - ...
        r'^-\s*\*\*(PASS|NEEDS_ATTENTION)\*\*\s*-',
        # 3. Bullet format without trailing dash: - **PASS** or - **NEEDS_ATTENTION**
        r'^-\s*\*\*(PASS|NEEDS_ATTENTION)\*\*\s*$',
    ]

    # Collect all matches with their positions
    all_matches: list[tuple[int, str]] = []

    for pattern in patterns:
        for match in re.finditer(pattern, output, re.IGNORECASE | re.MULTILINE):
            # Store (position, status)
            all_matches.append((match.end(), match.group(1).upper()))

    if all_matches:
        # Sort by position, use last match as final verdict
        all_matches.sort(key=lambda x: x[0])
        return ReviewStatus(all_matches[-1][1])

    # No explicit status marker found - check for standalone markers as fallback
    # Only in the last 500 chars to avoid false positives from prose
    tail = output[-500:] if len(output) > 500 else output

    # Fallback patterns for standalone markers (near end only)
    fallback_patterns = [
        # NEEDS_ATTENTION on its own line (more specific, check first)
        (r'(?:^|\n)\s*\*?\*?NEEDS_ATTENTION\*?\*?\s*(?:\n|$)', ReviewStatus.NEEDS_ATTENTION),
        # **PASS** on its own line
        (r'(?:^|\n)\s*\*\*PASS\*\*\s*(?:\n|$)', ReviewStatus.PASS),
        # PASS on its own line (but NOT "will PASS" or "PASS all tests")
        # Must be at line start or after sentence-ending punctuation
        (r'(?:^|\n)\s*PASS\s*(?:\n|$)', ReviewStatus.PASS),
    ]

    for pattern, status in fallback_patterns:
        if re.search(pattern, tail, re.IGNORECASE):
            return status

    # No clear marker found - default to NEEDS_ATTENTION (fail-safe)
    return ReviewStatus.NEEDS_ATTENTION


def build_review_prompt(
    state: WorkflowState,
    phase: str,
    diff_output: str,
    is_truncated: bool,
) -> str:
    """Build the prompt for the reviewer agent.

    Args:
        state: Current workflow state
        phase: Phase being reviewed ("fundamental" or "final")
        diff_output: Git diff output (full or stat-only)
        is_truncated: Whether diff was truncated due to size

    Returns:
        Formatted prompt string for the reviewer
    """
    plan_path = state.get_plan_path()

    prompt = f"""Review the code changes from the {phase} phase of implementation.

## Implementation Plan
File: {plan_path}
(Use codebase-retrieval to read relevant sections as needed)

## Code Changes
{diff_output}
"""

    if is_truncated:
        prompt += """
## Large Changeset Instructions
This is a large changeset. The diff above shows only the file summary.
Use `git diff -- <file_path>` to inspect specific files that need detailed review.
Focus on files most critical to the implementation plan.
"""

    prompt += """
## Review Instructions
1. Check that changes align with the implementation plan
2. Identify any issues, bugs, or missing functionality
3. Look for missing tests, error handling, or edge cases

## Output Format
End your review with one of these EXACT status lines:

**Status**: PASS

OR

**Status**: NEEDS_ATTENTION

If NEEDS_ATTENTION, list specific issues:
**Issues**:
1. [ISSUE_TYPE] Description of the issue
2. [ISSUE_TYPE] Description of the issue
...
"""

    return prompt


def _get_diff_for_review(state: WorkflowState) -> tuple[str, bool, bool]:
    """Get diff for review, using baseline if available.

    Uses baseline-anchored diff when diff_baseline_ref is set in state,
    otherwise falls back to legacy get_smart_diff() for backwards compatibility.

    Args:
        state: Current workflow state with optional diff_baseline_ref.

    Returns:
        Tuple of (diff_output, is_truncated, git_error).
    """
    if state.diff_baseline_ref:
        # Use baseline-anchored diff (recommended)
        return get_smart_diff_from_baseline(
            state.diff_baseline_ref,
            include_working_tree=True,  # Include uncommitted changes
        )
    else:
        # Fallback to legacy behavior (no baseline)
        return get_smart_diff()


def _run_rereview_after_fix(
    state: WorkflowState,
    log_dir: Path,
    phase: str,
    auggie_client: AuggieClient,
) -> bool | None:
    """Re-run review after auto-fix attempt.

    Offers the user the option to re-run the review after auto-fix
    has been applied. This helper centralizes the re-review logic
    to keep run_phase_review() simpler.

    Args:
        state: Current workflow state
        log_dir: Directory for log files
        phase: Phase identifier ("fundamental" or "final")
        auggie_client: AuggieClient instance to reuse

    Returns:
        True if re-review passed (workflow should continue),
        False if user wants to stop,
        None if re-review failed or user skipped (caller should fall through)
    """
    if not prompt_confirm("Run review again after auto-fix?", default=True):
        return None  # User skipped re-review, fall through to continue prompt

    print_step(f"Re-running {phase} phase review after auto-fix...")

    # Get updated diff using baseline if available
    diff_output, is_truncated, git_error = _get_diff_for_review(state)

    if git_error:
        print_warning("Could not retrieve git diff for re-review")
        return None  # Fall through to continue prompt

    if not diff_output.strip():
        print_info("No changes to review after auto-fix")
        return True  # No changes = pass

    # Build new prompt and run review
    prompt = build_review_prompt(state, phase, diff_output, is_truncated)

    try:
        success, output = auggie_client.run_print_with_output(
            prompt,
            agent=state.subagent_names["reviewer"],
            dont_save_session=True,
        )

        if not success:
            print_warning("Re-review execution returned failure")
            return None  # Fall through to continue prompt

        status = parse_review_status(output)

        if status == ReviewStatus.PASS:
            print_success(f"{phase.capitalize()} review after auto-fix: PASS")
            return True

        print_warning(f"{phase.capitalize()} review after auto-fix: NEEDS_ATTENTION")
        print_info("Issues remain after auto-fix. Please review manually.")
        return None  # Fall through to continue prompt

    except Exception as e:
        print_warning(f"Re-review execution failed: {e}")
        return None  # Fall through to continue prompt


def run_phase_review(
    state: WorkflowState,
    log_dir: Path,
    phase: str,
) -> bool:
    """Run review checkpoint and optionally auto-fix.

    Executes the spec-reviewer agent to validate completed work.
    If issues are found, offers the user the option to attempt
    automatic fixes using the implementer agent, and optionally
    re-run the review after fixes.

    Uses baseline-anchored diffs when available to ensure the review
    only inspects changes introduced by the current workflow, not
    pre-existing dirty changes.

    Args:
        state: Current workflow state
        log_dir: Directory for log files
        phase: Phase identifier ("fundamental" or "final")

    Returns:
        True if review passed or user chose to continue,
        False if user explicitly chose to stop after failed review
    """
    # Import here to avoid circular dependency
    from spec.workflow.autofix import run_auto_fix

    print_step(f"Running {phase} phase review...")

    # Get smart diff using baseline if available
    diff_output, is_truncated, git_error = _get_diff_for_review(state)

    if git_error:
        # Git command failed - prompt user instead of silently skipping
        print_warning("Could not retrieve git diff for review")
        print_info("The review cannot inspect code changes without git diff output.")
        if prompt_confirm("Continue workflow without code review?", default=True):
            return True
        else:
            print_info("Workflow stopped by user (could not retrieve diff for review)")
            return False

    if not diff_output.strip():
        print_info("No changes to review")
        return True

    # Build prompt
    prompt = build_review_prompt(state, phase, diff_output, is_truncated)

    # Run review
    auggie_client = AuggieClient()
    try:
        success, output = auggie_client.run_print_with_output(
            prompt,
            agent=state.subagent_names["reviewer"],
            dont_save_session=True,
        )
    except Exception as e:
        print_warning(f"Review execution failed: {e}")
        print_info("Continuing workflow despite review failure")
        return True  # Continue workflow on review crash (advisory behavior)

    # Check if execution succeeded before parsing output
    if not success:
        print_warning("Review execution returned failure (exit code non-zero)")
        print_info("Review output may be incomplete or unreliable")
        # Treat as NEEDS_ATTENTION for decision-making, but allow user to continue
        if prompt_confirm("Continue workflow despite review execution failure?", default=True):
            return True
        else:
            print_info("Workflow stopped by user after review execution failure")
            return False

    # Parse review result using robust parser (only when execution succeeded)
    status = parse_review_status(output)

    if status == ReviewStatus.PASS:
        print_success(f"{phase.capitalize()} review: PASS")
        return True

    # Review found issues
    print_warning(f"{phase.capitalize()} review: NEEDS_ATTENTION")

    # Offer auto-fix
    if prompt_confirm("Would you like to attempt auto-fix?", default=False):
        fix_success = run_auto_fix(state, output, log_dir)

        if fix_success:
            # Offer to re-run review after auto-fix
            re_review_result = _run_rereview_after_fix(
                state, log_dir, phase, auggie_client
            )
            if re_review_result is not None:
                return re_review_result
            # re_review_result is None means fall through to continue prompt
        else:
            print_warning("Auto-fix reported issues")

    # Ask user if they want to continue or stop
    if prompt_confirm("Continue workflow despite review issues?", default=True):
        return True
    else:
        print_info("Workflow stopped by user after review")
        return False


# Backwards-compatible aliases (underscore-prefixed)
_parse_review_status = parse_review_status
_build_review_prompt = build_review_prompt
_run_phase_review = run_phase_review


__all__ = [
    "ReviewStatus",
    "parse_review_status",
    "build_review_prompt",
    "run_phase_review",
    # Backwards-compatible aliases
    "_parse_review_status",
    "_build_review_prompt",
    "_run_phase_review",
]

