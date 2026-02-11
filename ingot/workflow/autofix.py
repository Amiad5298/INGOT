"""Auto-fix utilities for Step 3 execution.

This module provides utilities for automatically fixing issues
identified during code review. It uses the implementer agent
to address problems found by the reviewer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ingot.integrations.backends.base import AIBackend
from ingot.utils.console import (
    print_error,
    print_step,
    print_success,
    print_warning,
)

if TYPE_CHECKING:
    from ingot.workflow.state import WorkflowState

_MAX_REVIEW_FEEDBACK_LENGTH = 3000


def run_auto_fix(
    state: WorkflowState,
    review_feedback: str,
    log_dir: Path,
    backend: AIBackend,
) -> bool:
    """Attempt to fix issues identified in review.

    Spins up an implementer agent to address the issues found during
    code review. The agent receives the review feedback and attempts
    to fix the identified problems.

    Args:
        state: Current workflow state
        review_feedback: The review output containing identified issues
        log_dir: Directory for log files
        backend: AI backend instance for agent interactions

    Returns:
        True if fix was attempted successfully (agent completed),
        False if agent crashed or was cancelled
    """
    print_step("Attempting auto-fix based on review feedback...")

    if len(review_feedback) > _MAX_REVIEW_FEEDBACK_LENGTH:
        cut = review_feedback[:_MAX_REVIEW_FEEDBACK_LENGTH].rfind("\n")
        if cut <= 0:
            cut = _MAX_REVIEW_FEEDBACK_LENGTH
        review_feedback = (
            review_feedback[:cut]
            + "\n\n... [review feedback truncated — focus on the issues listed above]"
        )

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

    try:
        success, _ = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names.get("fixer", state.subagent_names["implementer"]),
            output_callback=lambda _line: None,
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
