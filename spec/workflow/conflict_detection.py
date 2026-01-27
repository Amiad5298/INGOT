"""Conflict detection for SPEC workflow.

This module provides semantic conflict detection between ticket descriptions
and user-provided context. It implements the "Fail-Fast Semantic Check" pattern
to identify contradictions early in the workflow.
"""

import re

from spec.integrations.auggie import AuggieClient
from spec.integrations.providers import GenericTicket
from spec.utils.logging import log_message
from spec.workflow.state import WorkflowState

# Prompt template for conflict detection between ticket and user context
CONFLICT_DETECTION_PROMPT_TEMPLATE = """Analyze the following ticket information and user-provided context for semantic conflicts.

TICKET INFORMATION:
{ticket_info}

USER-PROVIDED CONTEXT:
{user_context}

TASK: Determine if there are any semantic conflicts between the ticket and user context.
Conflicts include:
- Contradictory requirements (e.g., ticket says "add feature X" but user says "remove feature X")
- Scope mismatches (e.g., ticket is about backend but user context discusses frontend changes)
- Incompatible constraints (e.g., different target versions, conflicting technical approaches)

RESPOND IN EXACTLY THIS FORMAT:
CONFLICT: [YES or NO]
SUMMARY: [If YES, provide a 1-2 sentence summary of the conflict. If NO, write "No conflicts detected."]

Be conservative - only flag clear contradictions, not mere differences in detail level."""

# Regex patterns for parsing conflict detection response
CONFLICT_PATTERN = re.compile(r"CONFLICT\s*:\s*(YES|NO)", re.IGNORECASE)
SUMMARY_PATTERN = re.compile(r"SUMMARY\s*:\s*(.*)", re.IGNORECASE | re.DOTALL)


def _noop_callback(_: str) -> None:
    """No-op callback for silent LLM calls."""
    pass


def detect_context_conflict(
    ticket: GenericTicket,
    user_context: str,
    auggie: AuggieClient,
    state: WorkflowState,
) -> tuple[bool, str]:
    """Detect semantic conflicts between ticket description and user context.

    Uses a lightweight LLM call to identify contradictions or conflicts between
    the official ticket description and the user-provided additional context.

    This implements the "Fail-Fast Semantic Check" pattern:
    - Runs immediately after user context is collected
    - Uses semantic analysis (not brittle keyword matching)
    - Returns conflict info for advisory warnings (non-blocking)

    Args:
        ticket: GenericTicket with title and description (platform-agnostic)
        user_context: User-provided additional context
        auggie: Auggie CLI client
        state: Workflow state for accessing subagent configuration

    Returns:
        Tuple of (conflict_detected: bool, conflict_summary: str)
        - conflict_detected: True if semantic conflicts were found
        - conflict_summary: Description of the conflict(s) if any
    """
    # If no user context or no ticket description, no conflict is possible
    if not user_context.strip():
        return False, ""

    ticket_info = f"Title: {ticket.title or 'Not available'}\nDescription: {ticket.description or 'Not available'}"
    if not ticket.description and not ticket.title:
        return False, ""

    # Build prompt from template
    prompt = CONFLICT_DETECTION_PROMPT_TEMPLATE.format(
        ticket_info=ticket_info,
        user_context=user_context,
    )

    log_message("Running conflict detection between ticket and user context")

    try:
        # Use run_with_callback with a no-op callback to capture output silently
        success, output = auggie.run_with_callback(
            prompt,
            agent=state.subagent_names["planner"],
            output_callback=_noop_callback,
            dont_save_session=True,
        )

        if not success:
            log_message("Conflict detection LLM call failed")
            return False, ""

        # Parse the response using regex for robustness
        conflict_match = CONFLICT_PATTERN.search(output)
        conflict_detected = conflict_match is not None and conflict_match.group(1).upper() == "YES"

        # Extract summary
        summary = ""
        if conflict_detected:
            summary_match = SUMMARY_PATTERN.search(output)
            if summary_match:
                summary = summary_match.group(1).strip()

            if not summary:
                summary = "Potential conflict detected between ticket and user context."

        log_message(
            f"Conflict detection result: detected={conflict_detected}, summary={summary[:100]}"
        )
        return conflict_detected, summary

    except Exception as e:
        log_message(f"Conflict detection error: {e}")
        return False, ""


# Private alias for backward compatibility with existing imports
_detect_context_conflict = detect_context_conflict

__all__ = [
    "detect_context_conflict",
    "_detect_context_conflict",
    "CONFLICT_DETECTION_PROMPT_TEMPLATE",
    "CONFLICT_PATTERN",
    "SUMMARY_PATTERN",
    "_noop_callback",
]
