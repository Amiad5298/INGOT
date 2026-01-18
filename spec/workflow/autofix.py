"""Auto-fix utilities for Step 3 execution.

This module provides utilities for automatically fixing issues
identified during code review. It uses the implementer agent
to address problems found by the reviewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from spec.integrations.auggie import AuggieClient
from spec.utils.console import (
    print_error,
    print_step,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from spec.workflow.state import WorkflowState


def run_auto_fix(
    state: WorkflowState,
    review_feedback: str,
    log_dir: Path,
) -> bool:
    """Attempt to fix issues identified in review.

    Spins up an implementer agent to address the issues found during
    code review. The agent receives the review feedback and attempts
    to fix the identified problems.

    Args:
        state: Current workflow state
        review_feedback: The review output containing identified issues
        log_dir: Directory for log files

    Returns:
        True if fix was attempted successfully (agent completed),
        False if agent crashed or was cancelled
    """
    print_step("Attempting auto-fix based on review feedback...")

    prompt = f"""Fix the following issues identified during code review:

{review_feedback}

Implementation plan for context: {state.get_plan_path()}

Instructions:
1. Address each issue listed above
2. Do NOT introduce new features or refactor unrelated code
3. Focus only on fixing the identified problems
4. If a test is missing, create a minimal test that covers the gap
5. If error handling is missing, add appropriate handling

Do NOT commit any changes."""

    auggie_client = AuggieClient()

    try:
        success, _ = auggie_client.run_print_with_output(
            prompt,
            agent=state.subagent_names["implementer"],
            dont_save_session=True,
        )
        if success:
            print_success("Auto-fix completed")
        else:
            print_warning("Auto-fix reported issues")
        return success
    except Exception as e:
        print_error(f"Auto-fix failed: {e}")
        return False


# Backwards-compatible alias (underscore-prefixed)
_run_auto_fix = run_auto_fix


__all__ = [
    "run_auto_fix",
    # Backwards-compatible alias
    "_run_auto_fix",
]

