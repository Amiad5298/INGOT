"""Step 4: Update Documentation - Automated Doc Maintenance.

This module implements the fourth step of the workflow - automatically
updating documentation based on code changes made during the session.

Philosophy: Keep docs in sync with code. If code changed, docs should
reflect those changes before the user commits.
"""

from specflow.integrations.auggie import AuggieClient
from specflow.integrations.git import get_diff_from_baseline, is_dirty
from specflow.utils.console import print_header, print_info, print_success, print_warning
from specflow.workflow.state import WorkflowState


# Maximum diff size to avoid context overflow
MAX_DIFF_SIZE = 8000


def step_4_update_docs(state: WorkflowState) -> bool:
    """Execute Step 4: Update documentation based on code changes.

    This step:
    1. Checks if there are any changes to analyze
    2. Gets the git diff from the baseline commit
    3. Invokes the spec-doc-updater agent to analyze and update docs
    4. Reports what documentation was updated

    Args:
        state: Current workflow state

    Returns:
        True if documentation was updated successfully (or no updates needed)
    """
    print_header("Step 4: Update Documentation")

    # Check if there are any changes to analyze
    if not is_dirty() and not state.base_commit:
        print_info("No changes detected. Skipping documentation update.")
        return True

    # Get diff from baseline
    diff_content = get_diff_from_baseline(state.base_commit)
    if not diff_content or diff_content.strip() == "":
        print_info("No code changes to document. Skipping.")
        return True

    print_info("Analyzing code changes for documentation updates...")

    # Build prompt for doc-updater agent
    prompt = _build_doc_update_prompt(state, diff_content)

    # Use spec-doc-updater subagent
    auggie_client = AuggieClient()

    try:
        success, output = auggie_client.run_print_with_output(
            prompt,
            agent=state.subagent_names.get("doc_updater", "spec-doc-updater"),
            dont_save_session=True,
        )

        if success:
            print_success("Documentation update completed")
        else:
            print_warning("Documentation update reported issues (non-blocking)")

        # Always return True - this step is non-blocking per spec
        # Doc update failures should not fail the overall workflow
        return True

    except Exception as e:
        print_warning(f"Documentation update failed: {e}")
        # Don't fail the workflow for doc update issues
        return True


def _build_doc_update_prompt(state: WorkflowState, diff_content: str) -> str:
    """Build the prompt for the doc-updater agent.

    Args:
        state: Current workflow state
        diff_content: Git diff content from the session

    Returns:
        Formatted prompt string
    """
    # Truncate diff to avoid context overflow
    truncated_diff = diff_content[:MAX_DIFF_SIZE]
    if len(diff_content) > MAX_DIFF_SIZE:
        truncated_diff += "\n\n... (diff truncated due to size)"

    return f"""Update documentation for: {state.ticket.ticket_id}

## Task Summary
Review the code changes made in this workflow session and update any
documentation files that need to reflect these changes.

## Changes Made (git diff)
```diff
{truncated_diff}
```

## Instructions
1. Analyze what functionality was added or changed
2. Identify which documentation files need updates
3. Make targeted updates to keep docs in sync with code
4. Report what was updated

Focus on README.md, API docs, and any relevant documentation files.
Do NOT update docs for unchanged code."""


__all__ = ["step_4_update_docs"]

