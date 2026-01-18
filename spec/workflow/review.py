"""Code review utilities for Step 3 execution.

This module provides utilities for running code reviews during the
execution phase, including parsing review output, building review
prompts, and coordinating the review workflow with optional auto-fix.
"""

from __future__ import annotations

import re
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
from spec.workflow.git_utils import get_smart_diff

if TYPE_CHECKING:
    from spec.workflow.state import WorkflowState


def parse_review_status(output: str) -> str:
    """Parse review status from agent output.

    Extracts the final status marker from review output, looking for
    **Status**: PASS or **Status**: NEEDS_ATTENTION in the last occurrence.

    This parser is robust to:
    - Bold markers (**Status** or Status)
    - Whitespace variations
    - Case variations (PASS, Pass, pass)
    - Multiple occurrences (uses last one as final verdict)
    - PASS appearing in normal text (only counts if after Status: marker)

    Args:
        output: Review agent output text

    Returns:
        "PASS" if review passed, "NEEDS_ATTENTION" if issues found,
        or "NEEDS_ATTENTION" if status cannot be determined (fail-safe)

    Examples:
        >>> parse_review_status("**Status**: PASS\\n\\nLooks good!")
        'PASS'
        >>> parse_review_status("Status: NEEDS_ATTENTION\\n\\nIssues found")
        'NEEDS_ATTENTION'
        >>> parse_review_status("Some text with PASS in it\\n**Status**: NEEDS_ATTENTION")
        'NEEDS_ATTENTION'
        >>> parse_review_status("Ambiguous output")
        'NEEDS_ATTENTION'
    """
    if not output or not output.strip():
        return "NEEDS_ATTENTION"

    # Unified pattern to match status line with optional bold markers
    # Matches:
    #   **Status**: PASS, **Status**: NEEDS_ATTENTION
    #   Status: PASS, Status: NEEDS_ATTENTION
    #   With whitespace variations around the colon
    # Case-insensitive for the status keywords
    pattern = r'(?:\*\*)?Status(?:\*\*)?\s*:\s*(PASS|NEEDS_ATTENTION)'

    matches = list(re.finditer(pattern, output, re.IGNORECASE))

    if not matches:
        # No explicit status marker found - check for standalone markers as fallback
        # Only if they appear near the end (last 500 chars) to avoid false positives
        tail = output[-500:] if len(output) > 500 else output

        # Look for NEEDS_ATTENTION first (more specific)
        if re.search(r'\bNEEDS_ATTENTION\b', tail, re.IGNORECASE):
            return "NEEDS_ATTENTION"

        # Then look for PASS (but be more strict - must be on its own line or after punctuation)
        if re.search(r'(?:^|\n|[.!?]\s+)\*\*PASS\*\*|(?:^|\n|[.!?]\s+)PASS\s*(?:\n|$)', tail, re.IGNORECASE):
            return "PASS"

        # No clear marker found - default to NEEDS_ATTENTION (fail-safe)
        return "NEEDS_ATTENTION"

    # Use the last match as the final verdict
    last_match = matches[-1]
    status = last_match.group(1)

    return status.upper()


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
End your review with one of:
- **PASS** - Changes look good, ready to proceed
- **NEEDS_ATTENTION** - Issues found that should be addressed

If NEEDS_ATTENTION, list specific issues in this format:
**Issues**:
1. [ISSUE_TYPE] Description of the issue
2. [ISSUE_TYPE] Description of the issue
...
"""

    return prompt


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

    # Get smart diff (with git error handling)
    diff_output, is_truncated, git_error = get_smart_diff()

    if git_error:
        # Git command failed - warn but continue (advisory behavior)
        print_warning("Could not retrieve git diff for review")
        print_info("Continuing workflow (review could not inspect changes)")
        return True

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

    if status == "PASS":
        print_success(f"{phase.capitalize()} review: PASS")
        return True

    # Review found issues
    print_warning(f"{phase.capitalize()} review: NEEDS_ATTENTION")

    # Offer auto-fix
    if prompt_confirm("Would you like to attempt auto-fix?", default=False):
        fix_success = run_auto_fix(state, output, log_dir)

        if fix_success:
            # Offer to re-run review after auto-fix
            if prompt_confirm("Run review again after auto-fix?", default=True):
                print_step(f"Re-running {phase} phase review after auto-fix...")

                # Get updated diff
                diff_output_retry, is_truncated_retry, git_error_retry = get_smart_diff()

                if git_error_retry:
                    print_warning("Could not retrieve git diff for re-review")
                    # Fall through to continue prompt
                elif not diff_output_retry.strip():
                    print_info("No changes to review after auto-fix")
                    return True
                else:
                    # Build new prompt
                    prompt_retry = build_review_prompt(
                        state, phase, diff_output_retry, is_truncated_retry
                    )

                    # Re-run review
                    try:
                        success_retry, output_retry = auggie_client.run_print_with_output(
                            prompt_retry,
                            agent=state.subagent_names["reviewer"],
                            dont_save_session=True,
                        )

                        # Check execution success before parsing
                        if not success_retry:
                            print_warning("Re-review execution returned failure")
                            # Fall through to continue prompt
                        else:
                            status_retry = parse_review_status(output_retry)

                            if status_retry == "PASS":
                                print_success(
                                    f"{phase.capitalize()} review after auto-fix: PASS"
                                )
                                return True
                            else:
                                print_warning(
                                    f"{phase.capitalize()} review after auto-fix: NEEDS_ATTENTION"
                                )
                                print_info(
                                    "Issues remain after auto-fix. Please review manually."
                                )
                                # Fall through to continue prompt below

                    except Exception as e:
                        print_warning(f"Re-review execution failed: {e}")
                        # Fall through to continue prompt below
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
    "parse_review_status",
    "build_review_prompt",
    "run_phase_review",
    # Backwards-compatible aliases
    "_parse_review_status",
    "_build_review_prompt",
    "_run_phase_review",
]

