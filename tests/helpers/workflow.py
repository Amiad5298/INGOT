"""Workflow-related test helper utilities.

This module contains helper functions for extracting and inspecting
workflow-related data in tests.
"""

from spec.integrations.providers import GenericTicket


def get_ticket_from_workflow_call(mock_workflow_runner) -> GenericTicket | None:
    """Extract ticket from workflow runner call, handling both positional and keyword args.

    This helper is resilient to changes in how the ticket is passed to the workflow runner.

    Args:
        mock_workflow_runner: The mocked run_spec_driven_workflow function

    Returns:
        The GenericTicket passed to the workflow, or None if not found

    Note:
        Uses isinstance(x, GenericTicket) for reliable detection, avoiding false
        positives from MagicMock objects that have arbitrary hasattr() behavior.
    """
    if not mock_workflow_runner.called:
        return None

    call_args = mock_workflow_runner.call_args

    # Try kwargs first (preferred)
    if call_args.kwargs and "ticket" in call_args.kwargs:
        candidate = call_args.kwargs["ticket"]
        if isinstance(candidate, GenericTicket):
            return candidate

    # Fall back to positional args - scan for first GenericTicket instance
    for arg in call_args.args:
        if isinstance(arg, GenericTicket):
            return arg

    return None
