"""Step 1.5: Interactive Clarification Phase.

This module implements an interactive Q&A loop where the AI asks one
clarification question at a time about the plan, the user answers,
and then the plan is rewritten to incorporate all collected clarifications.
"""

from dataclasses import dataclass
from pathlib import Path

from ingot.integrations.backends.base import AIBackend
from ingot.ui.prompts import prompt_confirm, prompt_input
from ingot.utils.console import (
    console,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ingot.utils.errors import UserCancelledError
from ingot.utils.logging import log_message
from ingot.workflow.state import WorkflowState
from ingot.workflow.step1_plan import _display_plan_summary

# =============================================================================
# Constants
# =============================================================================

MAX_CLARIFICATION_ROUNDS = 10
NO_MORE_QUESTIONS = "NO_MORE_QUESTIONS"
_MAX_CONFLICT_SUMMARY_LENGTH = 500
_MIN_PLAN_LENGTH_RATIO = 0.5  # Safety check: rewritten plan must be >= 50% of original


def _noop_callback(line: str) -> None:
    """No-op callback for silent backend calls."""


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ClarificationQA:
    """A single clarification question-answer pair."""

    question: str
    answer: str


# =============================================================================
# Entry Point
# =============================================================================


def step_1_5_clarification(state: WorkflowState, backend: AIBackend) -> bool:
    """Execute Step 1.5: Interactive Clarification Phase.

    This step:
    1. Prompts user whether to run clarification
    2. Runs an interactive Q&A loop (one question at a time)
    3. Rewrites the plan to incorporate all clarifications

    Returns True always (non-blocking step).
    """
    print_header("Step 1.5: Interactive Clarification Phase")

    # Verify plan file exists
    plan_path = state.get_plan_path()
    if not plan_path.exists():
        print_warning("Plan file not found, skipping clarification phase.")
        log_message(f"Step 1.5 skipped: plan file not found at {plan_path}")
        return True

    # Prompt user
    print_info("The AI can review the plan and ask clarification questions about:")
    print_info("  - Ambiguous requirements")
    print_info("  - Missing technical details")
    print_info("  - Unclear dependencies or integration points")
    print_info("  - Edge cases not covered")
    console.print()

    if not prompt_confirm(
        "Would you like the AI to review the plan and ask clarification questions?",
        default=True,
    ):
        print_info("Skipping clarification phase.")
        return True

    # Print instructions
    print_step("Starting interactive clarification phase...")
    console.print()
    print_info("INSTRUCTIONS:")
    print_info("  - The AI will ask one question at a time")
    print_info("  - Answer each question when prompted")
    print_info("  - Type 'done', 'skip', 'exit', or 'quit' to stop early")
    print_info("  - Press Ctrl+C to cancel at any time")
    console.print()

    # Run interactive Q&A loop
    qa_pairs = _run_interactive_qa_loop(state, backend, plan_path)

    if not qa_pairs:
        print_info("No clarifications collected.")
        return True

    # Rewrite plan with collected clarifications
    print_step(f"Rewriting plan with {len(qa_pairs)} clarification(s)...")
    success = _rewrite_plan_with_clarifications(state, backend, plan_path, qa_pairs)

    if success:
        print_success("Plan updated with clarifications!")
        _display_plan_summary(plan_path)
    else:
        print_warning("Plan rewrite failed. Appending clarifications log as fallback.")
        _append_clarifications_log(plan_path, qa_pairs)
        _display_plan_summary(plan_path)

    return True


# =============================================================================
# Interactive Q&A Loop
# =============================================================================


def _run_interactive_qa_loop(
    state: WorkflowState,
    backend: AIBackend,
    plan_path: Path,
) -> list[ClarificationQA]:
    """Run the interactive Q&A loop, collecting one question at a time.

    Returns list of ClarificationQA pairs collected.
    """
    qa_pairs: list[ClarificationQA] = []

    for round_num in range(1, MAX_CLARIFICATION_ROUNDS + 1):
        # Build prompt for this round
        prompt = _build_single_question_prompt(
            plan_path=plan_path,
            state=state,
            previous_qa=qa_pairs,
            round_num=round_num,
        )

        # Call backend silently to get a question
        log_message(f"Step 1.5: Requesting question (round {round_num})")

        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["planner"],
            output_callback=_noop_callback,
            dont_save_session=True,
        )

        if not success:
            print_warning("AI backend failed to generate a question. Stopping Q&A loop.")
            log_message(f"Step 1.5: Backend failed at round {round_num}")
            break

        # Extract question from output
        question = _extract_question(output)

        if question is None:
            # AI signaled no more questions
            print_info("AI has no more clarification questions.")
            break

        # Display question to user
        console.print()
        console.print(f"[bold cyan]Question {round_num}:[/bold cyan] {question}")
        console.print()

        # Collect answer
        try:
            answer = prompt_input("Your answer:")
        except UserCancelledError:
            print_info("\nClarification cancelled by user.")
            break

        # Check for exit commands
        if answer.strip().lower() in {"done", "exit", "skip", "quit"}:
            print_info("Stopping clarification loop.")
            break

        # Skip empty answers
        if not answer.strip():
            print_info("Empty answer, skipping this question.")
            continue

        qa_pairs.append(ClarificationQA(question=question, answer=answer.strip()))
        log_message(f"Step 1.5: Collected Q&A pair {len(qa_pairs)}")

        # Ask if user wants to continue (unless at max rounds)
        if round_num < MAX_CLARIFICATION_ROUNDS:
            if not prompt_confirm("Continue with more questions?", default=True):
                break

    return qa_pairs


# =============================================================================
# Plan Rewrite
# =============================================================================


def _rewrite_plan_with_clarifications(
    state: WorkflowState,
    backend: AIBackend,
    plan_path: Path,
    qa_pairs: list[ClarificationQA],
) -> bool:
    """Rewrite the plan incorporating all collected clarifications.

    Returns True if the plan was successfully rewritten.
    """
    original_content = plan_path.read_text()
    original_length = len(original_content)

    # Build rewrite prompt
    prompt = _build_rewrite_prompt(plan_path, qa_pairs)

    success, output = backend.run_with_callback(
        prompt,
        subagent=state.subagent_names["planner"],
        output_callback=_noop_callback,
        dont_save_session=True,
    )

    if not success:
        log_message("Step 1.5: Plan rewrite backend call failed")
        return False

    # Read the rewritten plan
    if not plan_path.exists():
        log_message("Step 1.5: Plan file disappeared after rewrite")
        return False

    new_content = plan_path.read_text()
    new_length = len(new_content)

    # Safety check: if the rewritten plan is too short, it's likely corrupted
    if original_length > 0 and new_length < original_length * _MIN_PLAN_LENGTH_RATIO:
        print_warning(
            "Rewritten plan is significantly shorter than original. "
            "Restoring original and appending clarifications log."
        )
        log_message(
            f"Step 1.5: Safety check failed - new length {new_length} "
            f"< {_MIN_PLAN_LENGTH_RATIO * 100}% of original {original_length}"
        )
        plan_path.write_text(original_content)
        return False

    # If AI omitted the Clarifications Log section, append it
    if "## Clarifications Log" not in new_content:
        _append_clarifications_log(plan_path, qa_pairs)

    log_message("Step 1.5: Plan successfully rewritten with clarifications")
    return True


# =============================================================================
# Prompt Builders
# =============================================================================


def _build_single_question_prompt(
    plan_path: Path,
    state: WorkflowState,
    previous_qa: list[ClarificationQA],
    round_num: int,
) -> str:
    """Build prompt for generating a single clarification question."""
    # Build conflict context (only for the first round)
    conflict_context = ""
    if round_num == 1 and state.conflict_detected and state.conflict_summary:
        sanitized_summary = state.conflict_summary[:_MAX_CONFLICT_SUMMARY_LENGTH]
        if len(state.conflict_summary) > _MAX_CONFLICT_SUMMARY_LENGTH:
            sanitized_summary += "..."
        conflict_context = f"""
IMPORTANT: A conflict was detected between the ticket description and the user's additional context:
"{sanitized_summary}"

Your FIRST question should address this specific conflict to help resolve the ambiguity.

"""

    # Build previous Q&A context
    qa_context = ""
    if previous_qa:
        qa_lines = []
        for i, qa in enumerate(previous_qa, 1):
            qa_lines.append(f"Q{i}: {qa.question}")
            qa_lines.append(f"A{i}: {qa.answer}")
            qa_lines.append("")
        qa_context = f"""
Previously asked questions and answers:
{"\n".join(qa_lines)}
"""

    return f"""You are reviewing an implementation plan and asking clarification questions ONE AT A TIME.

Implementation plan file: {plan_path}
Read the plan file before asking your question.

{conflict_context}{qa_context}
Ask a SINGLE clarification question about any ambiguous or unclear aspect of the plan:
- Requirements that could be interpreted multiple ways
- Missing technical details needed for implementation
- Unclear dependencies or integration points
- Edge cases or error scenarios not covered
- Performance, security, or scalability considerations

IMPORTANT RULES:
- Ask exactly ONE question (not multiple)
- Do NOT repeat any previously asked question
- If the plan is already clear and comprehensive, or you have no more questions, respond with EXACTLY: {NO_MORE_QUESTIONS}
- Output ONLY the question text (no numbering, no prefix, no explanation)"""


def _build_rewrite_prompt(
    plan_path: Path,
    qa_pairs: list[ClarificationQA],
) -> str:
    """Build prompt for rewriting the plan with clarifications."""
    qa_section = []
    for i, qa in enumerate(qa_pairs, 1):
        qa_section.append(f"Q{i}: {qa.question}")
        qa_section.append(f"A{i}: {qa.answer}")
        qa_section.append("")

    return f"""Rewrite the implementation plan to incorporate the following clarifications.

CURRENT PLAN:
File: {plan_path}
Read the current plan file before rewriting.

CLARIFICATIONS COLLECTED:
{"\n".join(qa_section)}

INSTRUCTIONS:
1. Modify the relevant sections of the plan in-place to incorporate the answers
2. Do NOT remove or shorten existing plan content - only add/modify based on clarifications
3. At the end of the plan, add a "## Clarifications Log" section listing all Q&A pairs for audit
4. Save the updated plan to: {plan_path}

The updated plan should be comprehensive and reflect all the clarifications provided."""


# =============================================================================
# Helpers
# =============================================================================


def _extract_question(output: str | None) -> str | None:
    """Extract a clarification question from AI output.

    Returns None if the AI signaled no more questions (NO_MORE_QUESTIONS sentinel).
    Returns the cleaned question text otherwise.
    """
    if not output or not output.strip():
        return None

    text = output.strip()

    # Check for sentinel
    if NO_MORE_QUESTIONS in text:
        return None

    # Take the meaningful content - strip any leading/trailing whitespace per line
    # and join non-empty lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    return " ".join(lines)


def _append_clarifications_log(plan_path: Path, qa_pairs: list[ClarificationQA]) -> None:
    """Append a Clarifications Log section to the plan file."""
    content = plan_path.read_text()

    log_section = "\n\n## Clarifications Log\n\n"
    for i, qa in enumerate(qa_pairs, 1):
        log_section += f"**Q{i}:** {qa.question}\n"
        log_section += f"**A{i}:** {qa.answer}\n\n"

    plan_path.write_text(content + log_section)
    log_message(f"Step 1.5: Appended Clarifications Log with {len(qa_pairs)} Q&A pair(s)")


__all__ = [
    "step_1_5_clarification",
]
