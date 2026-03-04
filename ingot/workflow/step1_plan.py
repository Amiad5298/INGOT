"""Step 1: Create Implementation Plan.

This module implements the first step of the workflow - creating
an implementation plan based on the Jira ticket.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ingot.integrations.backends.base import AIBackend
from ingot.integrations.git import find_repo_root
from ingot.ui.menus import ReviewChoice, show_plan_review_menu
from ingot.ui.prompts import prompt_enter, prompt_input
from ingot.utils.console import (
    console,
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from ingot.utils.logging import log_message
from ingot.validation.base import ValidationContext, ValidationReport, ValidationSeverity
from ingot.validation.plan_fixer import PlanFixer
from ingot.validation.plan_validators import FileExistsValidator, create_plan_validator_registry
from ingot.workflow.constants import (
    MAX_GENERATION_ATTEMPTS,
    MAX_REVIEW_ITERATIONS,
    RESEARCHER_SECTION_HEADINGS,
    noop_output_callback,
)
from ingot.workflow.events import format_run_directory
from ingot.workflow.state import WorkflowState

if TYPE_CHECKING:
    from ingot.discovery.file_index import FileIndex

# Robust ANSI/terminal escape sequence patterns (ECMA-48 compliant).
# Matches:
# - CSI sequences: \x1b[ followed by parameter bytes (0x30-0x3f, including ?),
#   intermediate bytes (0x20-0x2f), and a final byte (0x40-0x7e).
#   Examples: \x1b[32m (color), \x1b[?25l (hide cursor), \x1b[38;2;255;0;0m (24-bit color)
# - OSC sequences: \x1b] ... ST (terminated by \x1b\\ or \x07).
#   Examples: \x1b]0;title\x07 (set window title)
# - Character set designation: \x1b( or \x1b) followed by a charset ID.
#
# Known limitation: Does not match bare two-byte ESC sequences like \x1bM
# (reverse index) or \x1bc (terminal reset). These are rare in AI CLI output.
_ANSI_RE = re.compile(
    r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]"  # CSI sequences
    r"|\x1b\].*?(?:\x1b\\|\x07)"  # OSC sequences
    r"|\x1b[()][A-Z0-9]"  # Character set designation
)

# Matches <thinking>...</thinking> blocks (case-insensitive, multi-line).
_THINKING_BLOCK_RE = re.compile(
    r"<thinking>.*?</thinking>",
    re.DOTALL | re.IGNORECASE,
)

# Maximum character limits for replan prompt sections to keep prompt size reasonable.
_REPLAN_PLAN_EXCERPT_LIMIT = 4000
_REPLAN_FEEDBACK_EXCERPT_LIMIT = 3000

# Character limit for the existing-plan excerpt in AI-fix prompts.
_FIX_PLAN_EXCERPT_LIMIT = 8000

# Source-label constants used in prompts to tag data provenance.
_SOURCE_VERIFIED = "[SOURCE: VERIFIED PLATFORM DATA]"
_SOURCE_UNVERIFIED = "[SOURCE: NO VERIFIED PLATFORM DATA]"
_UNVERIFIED_NOTE = (
    "NOTE: The platform returned no verified content for this ticket. "
    'Do NOT reference "the ticket" as a source of requirements.'
)

# Default researcher context truncation budget (chars, ~3000 tokens).
# Can be overridden via Settings.researcher_context_budget.
_DEFAULT_RESEARCHER_CONTEXT_BUDGET = 12000

# Section priority order for truncation: first entry = highest priority, last = first dropped.
# Uses RESEARCHER_SECTION_HEADINGS directly — the truncation priority matches
# the canonical heading order defined in constants.py.


# Ticket signal categories for conditional logic.
_TICKET_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "metric": (
        "metric",
        "metrics",
        "gauge",
        "counter",
        "histogram",
        "prometheus",
        "grafana",
        "datadog",
    ),
    "alert": (
        "alert",
        "alerting",
        "pagerduty",
        "opsgenie",
        "on-call",
        "oncall",
        "slo",
        "sli",
        "sla",
    ),
    "monitor": (
        "monitor",
        "monitoring",
        "observability",
        "dashboard",
        "health check",
        "healthcheck",
    ),
    "endpoint": ("endpoint", "api", "rest", "graphql", "grpc", "controller", "handler", "route"),
    "migration": (
        "migration",
        "migrate",
        "schema",
        "flyway",
        "liquibase",
        "alembic",
        "database change",
    ),
    "config": (
        "config",
        "configuration",
        "property",
        "properties",
        "setting",
        "feature flag",
        "toggle",
    ),
    "refactor": (
        "refactor",
        "refactoring",
        "cleanup",
        "reorganize",
        "restructure",
        "rename",
        "extract",
    ),
    "security": (
        "security",
        "auth",
        "authentication",
        "authorization",
        "oauth",
        "jwt",
        "rbac",
        "permission",
    ),
    "test": ("test", "testing", "coverage", "e2e", "integration test", "unit test", "test suite"),
}

# Pre-compiled word-boundary patterns for each signal category (avoids
# re-compiling on every call to _extract_ticket_signals).
_TICKET_SIGNAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(rf"\b{re.escape(kw)}\b") for kw in keywords]
    for category, keywords in _TICKET_SIGNAL_KEYWORDS.items()
}


def _extract_ticket_signals(text: str) -> list[str]:
    """Extract category signals from ticket text via keyword matching.

    Args:
        text: Combined ticket title + description.

    Returns:
        List of signal category names (e.g., ["metric", "alert"]).
    """
    if not text:
        return []

    text_lower = text.lower()
    signals: list[str] = []
    for category, patterns in _TICKET_SIGNAL_PATTERNS.items():
        if any(pat.search(text_lower) for pat in patterns):
            signals.append(category)
    return signals


# =============================================================================
# Log Directory Management
# =============================================================================


def _get_log_base_dir() -> Path:
    """Get the base directory for run logs."""
    env_dir = os.environ.get("INGOT_LOG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(".ingot/runs")


def _create_plan_log_dir(safe_ticket_id: str) -> Path:
    """Create a timestamped log directory for plan generation.

    safe_ticket_id MUST be sanitized (use ticket.safe_filename_stem) -
    raw ticket IDs may contain unsafe chars like '/'.
    """
    base_dir = _get_log_base_dir()
    plan_dir = base_dir / safe_ticket_id / "plan_generation"
    plan_dir.mkdir(parents=True, exist_ok=True)
    return plan_dir


# =============================================================================
# Plan Generation Functions
# =============================================================================


def _generate_plan_with_tui(
    state: WorkflowState,
    plan_path: Path,
    backend: AIBackend,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> tuple[bool, str]:
    """Generate plan with TUI progress display using subagent.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan should be saved.
        backend: AI backend for agent calls.
        researcher_context: Optional researcher output to inject into the prompt.
        local_discovery_context: Pre-verified local discovery markdown.

    Returns:
        Tuple of (success, captured_output).
    """
    # Lazy import: startup-perf optimization, NOT circular-dep workaround —
    # InlineRunner only imports from ingot.ui.log_buffer and ingot.utils.console
    from ingot.ui.inline_runner import InlineRunner

    # Create log directory and log path (use safe_filename_stem for paths)
    log_dir = _create_plan_log_dir(state.ticket.safe_filename_stem)
    log_path = log_dir / f"{format_run_directory()}.log"

    ui = InlineRunner(
        status_message="Generating implementation plan...",
        ticket_id=state.ticket.id,  # Keep original ID for display
    )
    ui.set_log_path(log_path)

    # Use plan_mode only for backends that map it to a CLI flag;
    # others (Auggie, Codex) can write the plan file directly.
    use_plan_mode = backend.supports_plan_mode

    # Build minimal prompt - agent has the instructions
    prompt = _build_minimal_prompt(
        state,
        plan_path,
        plan_mode=use_plan_mode,
        researcher_context=researcher_context,
        local_discovery_context=local_discovery_context,
    )

    def _work() -> tuple[bool, str]:
        return backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["planner"],
            output_callback=ui.handle_output_line,
            dont_save_session=True,
            plan_mode=use_plan_mode,
        )

    success, output = ui.run_with_work(_work)

    # Check if user requested quit
    if ui.check_quit_requested():
        print_warning("Plan generation cancelled by user.")
        return False, ""

    ui.print_summary(success)
    return success, output


def _build_minimal_prompt(
    state: WorkflowState,
    plan_path: Path,
    *,
    plan_mode: bool = False,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> str:
    """Build minimal prompt for plan generation.

    The subagent has detailed instructions - we just pass context.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan should be saved.
        plan_mode: If True, instruct the AI to output the plan to stdout
            instead of writing a file (for read-only backends).
        researcher_context: Optional researcher output to inject into the prompt.
        local_discovery_context: Pre-verified local discovery markdown.
    """
    source_label = _SOURCE_VERIFIED if state.spec_verified else _SOURCE_UNVERIFIED

    prompt = f"""Create implementation plan for: {state.ticket.id}

{source_label}
Ticket: {state.ticket.title or state.ticket.branch_summary or "Not available"}
Description: {state.ticket.description or "Not available"}"""

    if not state.spec_verified:
        prompt += f"\n{_UNVERIFIED_NOTE}"

    # Add user constraints if provided
    if state.user_constraints:
        prompt += f"""

[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]
{state.user_constraints}"""

    # Inject local discovery context (deterministic ground truth)
    if local_discovery_context:
        prompt += f"""

[SOURCE: LOCAL DISCOVERY (deterministically verified)]
The following codebase facts were discovered by deterministic local tools.
These are verified ground truth — do NOT contradict them. If a pattern source
has `<!-- CITATION_MISMATCH -->`, do NOT use that pattern — search for the
correct one instead.

{local_discovery_context}"""

    # Inject researcher context if provided
    if researcher_context:
        trimmed = _truncate_researcher_context(
            researcher_context, budget=state.researcher_context_budget
        )
        prompt += f"""

[SOURCE: CODEBASE DISCOVERY (from automated research)]
The following codebase context was discovered by a research agent. Use it as your
primary source of truth for file paths, code patterns, and call sites. Do NOT
re-search for information already provided here.

{trimmed}"""
    else:
        if not local_discovery_context:
            prompt += """

[NOTE: No automated codebase discovery was performed for this ticket.]
You must independently explore the codebase to discover relevant files,
patterns, and call sites before creating the plan."""

    if plan_mode:
        prompt += """

Output the complete implementation plan in Markdown format to stdout.
Do not attempt to create or write any files.

Codebase context will be retrieved automatically."""
    else:
        prompt += f"""

Save the plan to: {plan_path}

Codebase context will be retrieved automatically."""

    return prompt


def build_fix_prompt(
    state: WorkflowState,
    plan_path: Path,
    existing_plan: str,
    validation_feedback: str,
    *,
    plan_mode: bool = False,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> str:
    """Build prompt that asks the AI to fix specific validation errors in an existing plan.

    Unlike full regeneration, this sends the current plan + validation errors
    and instructs the AI to fix only the flagged issues.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan should be saved.
        existing_plan: Current plan content (will be truncated if too long).
        validation_feedback: Formatted validation errors/warnings.
        plan_mode: If True, instruct AI to output to stdout instead of writing a file.
        researcher_context: Optional researcher output for context during fixes.
        local_discovery_context: Pre-verified local discovery markdown.
    """
    if len(existing_plan) <= _FIX_PLAN_EXCERPT_LIMIT:
        plan_excerpt = existing_plan
    else:
        # Keep both the beginning and end of the plan so the AI sees
        # the overall structure *and* trailing sections (which are
        # often the ones flagged as missing by validators).
        head_budget = _FIX_PLAN_EXCERPT_LIMIT * 2 // 3
        tail_budget = _FIX_PLAN_EXCERPT_LIMIT - head_budget
        plan_excerpt = (
            existing_plan[:head_budget]
            + "\n\n... [middle truncated] ...\n\n"
            + existing_plan[-tail_budget:]
        )

    ticket_source_label = _SOURCE_VERIFIED if state.spec_verified else _SOURCE_UNVERIFIED

    prompt = f"""Fix the validation errors in the existing implementation plan.

## Ticket
{ticket_source_label}
ID: {state.ticket.id}
Title: {state.ticket.title or state.ticket.branch_summary or "Not available"}
Description: {state.ticket.description or "Not available"}"""

    if not state.spec_verified:
        prompt += f"\n{_UNVERIFIED_NOTE}"

    prompt += f"""

## Current Plan (needs fixes)
{plan_excerpt}

## Validation Errors to Fix
{validation_feedback}

## Instructions
1. Read the validation errors above carefully
2. Fix ONLY the issues flagged — do not rewrite unrelated sections
3. Preserve the overall structure and content of the plan
4. Output the complete fixed plan (not just the changed parts)"""

    if plan_mode:
        prompt += """

Output the complete fixed implementation plan in Markdown format to stdout.
Do not attempt to create or write any files."""
    else:
        prompt += f"""

Save the fixed plan to: {plan_path}"""

    if state.user_constraints:
        prompt += f"""

[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]
{state.user_constraints}"""

    # Provide verified context so the AI can fix issues with correct information
    if local_discovery_context:
        prompt += f"""

[SOURCE: LOCAL DISCOVERY (deterministically verified)]
Use these verified facts when fixing file path errors or missing references:

{local_discovery_context}"""

    if researcher_context:
        trimmed = _truncate_researcher_context(
            researcher_context, budget=state.researcher_context_budget
        )
        prompt += f"""

[SOURCE: CODEBASE DISCOVERY (from automated research)]
Reference this context when fixing pattern citations or missing call sites:

{trimmed}"""

    return prompt


def fix_plan_with_ai(
    state: WorkflowState,
    plan_path: Path,
    backend: AIBackend,
    existing_plan: str,
    validation_feedback: str,
    *,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> tuple[bool, str]:
    """Ask the AI to fix specific validation errors in the existing plan.

    This is a lightweight alternative to full regeneration — it sends the
    current plan + error list and asks for targeted fixes only.

    Returns:
        Tuple of (success, output).
    """
    use_plan_mode = backend.supports_plan_mode

    prompt = build_fix_prompt(
        state,
        plan_path,
        existing_plan,
        validation_feedback,
        plan_mode=use_plan_mode,
        researcher_context=researcher_context,
        local_discovery_context=local_discovery_context,
    )

    try:
        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["planner"],
            output_callback=noop_output_callback,
            dont_save_session=True,
            plan_mode=use_plan_mode,
        )
    except Exception as e:
        print_error(f"AI fix attempt failed: {e}")
        return False, ""

    if not success:
        print_error("AI fix attempt returned failure")
        return False, ""

    return success, output


# =============================================================================
# Researcher Agent Functions
# =============================================================================


def _run_local_discovery(
    state: WorkflowState,
    repo_root: Path,
    file_index: "FileIndex | None",
) -> str:
    """Run local discovery tools to produce deterministic codebase context.

    Uses :class:`ContextBuilder` to orchestrate FileIndex, GrepEngine,
    ManifestParser, and TestMapper. Returns a markdown report suitable
    for injection into the researcher and planner prompts.

    Returns empty string if discovery produces no results or fails.
    """
    try:
        from ingot.discovery.context_builder import ContextBuilder, extract_keywords

        # Extract keywords from ticket text
        ticket_text = " ".join(filter(None, [state.ticket.title, state.ticket.description]))
        keywords = extract_keywords(ticket_text)
        if not keywords:
            log_message(
                "Local discovery: no keywords extracted from ticket text; "
                "running manifest/module discovery only"
            )

        builder = ContextBuilder(repo_root)
        report = builder.build(keywords=keywords, file_index=file_index)

        if report.is_empty:
            log_message("Local discovery: report is empty, skipping")
            return ""

        markdown = report.to_markdown()
        log_message(
            f"Local discovery: produced {len(markdown)} chars "
            f"({len(keywords)} keywords, "
            f"{sum(len(v) for v in report.keyword_matches.values())} matches)"
        )
        return markdown
    except Exception as exc:
        log_message(f"Local discovery failed (non-blocking): {exc}")
        return ""


def _run_researcher(
    state: WorkflowState,
    backend: AIBackend,
    *,
    local_discovery_context: str = "",
) -> tuple[bool, str]:
    """Run the researcher agent to discover codebase context.

    Args:
        state: Current workflow state.
        backend: AI backend for agent calls.
        local_discovery_context: Pre-verified local discovery markdown to
            inject into the researcher prompt as ground truth.

    Returns (success, researcher_output_markdown).
    """
    # Lazy import: startup-perf optimization, NOT circular-dep workaround —
    # InlineRunner only imports from ingot.ui.log_buffer and ingot.utils.console
    from ingot.ui.inline_runner import InlineRunner

    researcher_name = state.subagent_names.get("researcher")
    if not researcher_name:
        log_message("No researcher agent configured, skipping discovery phase")
        return False, ""

    source_label = _SOURCE_VERIFIED if state.spec_verified else _SOURCE_UNVERIFIED

    prompt = f"""Research the codebase for: {state.ticket.id}

{source_label}
Ticket: {state.ticket.title or state.ticket.branch_summary or "Not available"}
Description: {state.ticket.description or "Not available"}"""

    if state.user_constraints:
        prompt += f"""

[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]
{state.user_constraints}"""

    # Inject local discovery context as deterministically verified facts
    if local_discovery_context:
        prompt += f"""

[SOURCE: LOCAL DISCOVERY (deterministically verified)]
The following codebase facts were discovered by deterministic local tools (file
indexing, regex search, build manifest parsing, test mapping). These are verified
ground truth — do NOT contradict them. Your role is to interpret these facts,
identify the most relevant patterns, and fill gaps the local tools could not
cover (e.g., semantic understanding of code, architectural intent).

{local_discovery_context}"""

    ui = InlineRunner(
        status_message="Researching codebase...",
        ticket_id=state.ticket.id,
    )

    def _work() -> tuple[bool, str]:
        return backend.run_with_callback(
            prompt,
            subagent=researcher_name,
            output_callback=ui.handle_output_line,
            dont_save_session=True,
        )

    try:
        success, output = ui.run_with_work(_work)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        log_message(f"Researcher agent failed: {e}")
        return False, ""

    if ui.check_quit_requested():
        return False, ""

    ui.print_summary(success)
    return success, output


def _truncate_researcher_context(
    context: str, budget: int = _DEFAULT_RESEARCHER_CONTEXT_BUDGET
) -> str:
    """Truncate researcher context to fit within character budget.

    Preserves sections in priority order. When budget is exceeded, drops
    lowest-priority sections entirely, then truncates within the last
    kept section.

    Returns truncated context. Prepends a note header if truncation occurred.
    """
    # Header prepended when truncation occurs — account for its length in the budget.
    _TRUNCATION_HEADER = (
        "[NOTE: Research context truncated to fit budget. Full output saved to research file.]\n\n"
    )

    if len(context) <= budget:
        return context

    # Reserve space for the header so the final output stays within budget.
    effective_budget = budget - len(_TRUNCATION_HEADER)

    # Split context into sections by ### headings
    sections: list[tuple[str, str]] = []  # (heading, content)
    current_heading = ""
    current_lines: list[str] = []

    for line in context.splitlines():
        if line.strip().startswith("### "):
            if current_heading or current_lines:
                sections.append((current_heading, "\n".join(current_lines)))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Add final section
    if current_heading or current_lines:
        sections.append((current_heading, "\n".join(current_lines)))

    # Build a map of heading -> (heading, content)
    section_map: dict[str, tuple[str, str]] = {}
    for heading, content in sections:
        section_map[heading] = (heading, content)

    # Accumulate sections in priority order
    result_parts: list[str] = []
    total_len = 0
    truncated = False

    for priority_heading in RESEARCHER_SECTION_HEADINGS:
        if priority_heading not in section_map:
            continue
        heading, content = section_map[priority_heading]
        section_text = f"{heading}\n{content}"
        # Account for "\n" separator between sections (first section has no separator)
        separator_len = 1 if result_parts else 0
        if total_len + separator_len + len(section_text) <= effective_budget:
            result_parts.append(section_text)
            total_len += separator_len + len(section_text)
        else:
            # Truncate within this section
            remaining = effective_budget - total_len
            if remaining > len(heading) + 20:  # Only include if meaningful content fits
                truncated_content = content[: remaining - len(heading) - 5]
                # Cut at last newline to avoid mid-line truncation
                last_nl = truncated_content.rfind("\n")
                if last_nl > 0:
                    truncated_content = truncated_content[:last_nl]
                result_parts.append(f"{heading}\n{truncated_content}\n...")
            truncated = True
            break

    result = "\n".join(result_parts)

    if truncated or len(result) < len(context):
        result = _TRUNCATION_HEADER + result

    return result


# =============================================================================
# Researcher Output Validation
# =============================================================================


def _validate_researcher_paths(researcher_output: str, repo_root: Path | None) -> list[str]:
    """Validate file paths in researcher output against the filesystem.

    Runs the FileExistsValidator on the researcher output to catch
    hallucinated file paths before they propagate to the planner.

    Returns a list of invalid path strings (empty if all paths are valid).
    """
    if not researcher_output.strip() or repo_root is None:
        return []

    validator = FileExistsValidator()
    context = ValidationContext(repo_root=repo_root)
    findings = validator.validate(researcher_output, context)

    return [f.message for f in findings if f.severity == ValidationSeverity.ERROR]


def _annotate_researcher_warnings(researcher_output: str, invalid_paths: list[str]) -> str:
    """Prepend warnings about invalid paths to researcher output.

    Injects a warning block at the top of the researcher context so the
    planner knows which paths from the researcher are unreliable.
    """
    if not invalid_paths:
        return researcher_output

    warning_lines = [
        "[WARNING: The following paths from the researcher could not be verified",
        "on the filesystem. Do NOT use them without independently verifying:]",
    ]
    for msg in invalid_paths:
        warning_lines.append(f"  - {msg}")
    warning_lines.append("")

    return "\n".join(warning_lines) + "\n" + researcher_output


def _verify_researcher_citations(researcher_output: str, repo_root: Path | None) -> str:
    """Verify citations in researcher output and annotate mismatches.

    Runs the :class:`CitationVerifier` to deterministically check that
    ``Source: file:line-line`` citations actually match the file content.
    Returns the annotated researcher output.
    """
    if not researcher_output.strip() or repo_root is None:
        return researcher_output

    try:
        from ingot.discovery.citation_verifier import CitationVerifier

        verifier = CitationVerifier(repo_root)
        annotated, checks = verifier.verify_citations(researcher_output)

        mismatches = sum(1 for c in checks if not c.is_verified)
        if mismatches:
            log_message(f"CitationVerifier: {mismatches}/{len(checks)} citations have mismatches")
        return annotated
    except Exception as exc:
        log_message(f"CitationVerifier failed (non-blocking): {exc}")
        return researcher_output


# =============================================================================
# Plan Validation Functions
# =============================================================================


def _validate_plan(
    plan_content: str,
    state: WorkflowState,
    researcher_output: str = "",
    repo_root: Path | None = None,
) -> ValidationReport:
    """Run all registered plan validators.

    Args:
        repo_root: Pre-computed repository root. Avoids redundant
            ``find_repo_root()`` calls when invoked inside a retry loop.
    """
    registry = create_plan_validator_registry(researcher_output=researcher_output)
    context = ValidationContext(
        repo_root=repo_root,
        ticket_id=state.ticket.id,
        ticket_signals=state.ticket_signals,
    )
    return registry.validate_all(plan_content, context)


def _display_validation_report(report: ValidationReport) -> None:
    """Display validation findings to the user."""
    if not report.findings:
        return
    console.print()
    print_step("Plan Validation Results:")
    for finding in report.findings:
        severity_prefix = {
            ValidationSeverity.ERROR: "[red]ERROR[/red]",
            ValidationSeverity.WARNING: "[yellow]WARN[/yellow]",
            ValidationSeverity.INFO: "[dim]INFO[/dim]",
        }[finding.severity]
        console.print(f"  {severity_prefix} [{finding.validator_name}] {finding.message}")
        if finding.suggestion:
            console.print(f"         Suggestion: {finding.suggestion}")
    if report.error_count:
        console.print()
        print_warning(
            f"Plan has {report.error_count} error(s) and {report.warning_count} warning(s)"
        )
    console.print()


def _format_validation_feedback(report: ValidationReport) -> str:
    """Format actionable validation findings for retry prompt injection.

    Only includes ERROR and WARNING findings. Returns empty string if no
    actionable findings exist.
    """
    lines: list[str] = []
    for finding in report.findings:
        if finding.severity not in (ValidationSeverity.ERROR, ValidationSeverity.WARNING):
            continue
        severity = "ERROR" if finding.severity == ValidationSeverity.ERROR else "WARNING"
        line = f"- [{severity}] {finding.message}"
        if finding.suggestion:
            line += f" — Suggestion: {finding.suggestion}"
        lines.append(line)
    return "\n".join(lines)


# =============================================================================
# Plan Extraction
# =============================================================================


def _extract_plan_markdown(output: str) -> str:
    """Extract clean markdown plan from CLI output.

    Strips ANSI escape codes, ``<thinking>`` blocks, tool-call logs,
    and other noise. Looks for the first markdown heading (any level)
    and returns everything from there. Falls back to full output if no
    headings found.

    Known limitation: Heading detection does not account for fenced code
    blocks — a ``# comment`` inside a code fence would be matched as a
    heading. This is low risk for typical plan output.
    """
    output = _ANSI_RE.sub("", output)
    output = _THINKING_BLOCK_RE.sub("", output)
    lines = output.splitlines()

    # Find first markdown heading (any level: #, ##, ###, etc.)
    start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") and stripped.lstrip("#").startswith(" "):
            start_idx = i
            break

    # Strip trailing empty lines
    content = "\n".join(lines[start_idx:]).rstrip()
    return content if content else output.strip()


def _build_file_index(repo_root: Path | None) -> "FileIndex | None":
    """Build a FileIndex for the repository, or None if unavailable.

    Lazy-imports FileIndex to avoid import-time cost.
    """
    if repo_root is None:
        return None
    try:
        from ingot.discovery.file_index import FileIndex

        idx = FileIndex(repo_root)
        if idx.file_count > 0:
            log_message(f"Built FileIndex with {idx.file_count} files")
            return idx
        log_message("FileIndex is empty (no git-tracked files)")
        print_warning("No git-tracked files found — local discovery will be skipped.")
        return None
    except Exception as exc:
        log_message(f"FileIndex build failed: {exc}")
        print_warning(f"Local discovery unavailable: {exc}")
        return None


def step_1_create_plan(state: WorkflowState, backend: AIBackend) -> bool:
    """Execute Step 1: Create implementation plan.

    This step runs a 3-phase pipeline:
    1. Discovery: Researcher agent explores the codebase
    2. Synthesis: Planner agent creates a plan from verified researcher output
    3. Inspection: Python validators check the plan for structural issues

    If validation finds errors, offers a retry (up to MAX_GENERATION_ATTEMPTS).
    Then proceeds to the standard user review loop.

    Note: Ticket information is already fetched in the workflow runner
    before this step is called. Clarification is handled separately
    in step 1.5 (step1_5_clarification.py).
    """
    print_header("Step 1: Create Implementation Plan")

    # Ensure specs directory exists
    state.specs_dir.mkdir(parents=True, exist_ok=True)

    # Display ticket information (already fetched earlier)
    if state.ticket.title:
        print_info(f"Ticket: {state.ticket.title}")
    if state.ticket.description:
        print_info(f"Description: {state.ticket.description[:200]}...")

    plan_path = state.get_plan_path()
    researcher_output = ""

    # Extract ticket signals for conditional logic
    ticket_text = " ".join(filter(None, [state.ticket.title, state.ticket.description]))
    state.ticket_signals = _extract_ticket_signals(ticket_text)
    if state.ticket_signals:
        log_message(f"Ticket signals: {state.ticket_signals}")

    # Build FileIndex for local discovery (used by PlanFixer, CitationVerifier, ContextBuilder)
    repo_root = find_repo_root()
    file_index = _build_file_index(repo_root)

    # Phase 0: Local Discovery (deterministic, before AI agents)
    local_discovery_markdown = ""
    if repo_root is not None:
        local_discovery_markdown = _run_local_discovery(state, repo_root, file_index)

    # Phase 1: Discovery (runs once — not repeated on retry)
    researcher_name = state.subagent_names.get("researcher")
    if researcher_name:
        print_step("Researching codebase...")
        researcher_success, researcher_output = _run_researcher(
            state, backend, local_discovery_context=local_discovery_markdown
        )
        if researcher_success and researcher_output.strip():
            # Validate researcher paths to catch hallucinations early
            invalid_paths = _validate_researcher_paths(researcher_output, repo_root)
            if invalid_paths:
                print_warning(
                    f"Researcher output has {len(invalid_paths)} unverified path(s) "
                    f"— planner will be warned"
                )
                log_message(f"Researcher invalid paths: {invalid_paths}")
                researcher_output = _annotate_researcher_warnings(researcher_output, invalid_paths)

            # Verify citations (Source: file:line) against actual file content
            researcher_output = _verify_researcher_citations(researcher_output, repo_root)

            # Persist researcher output AFTER annotation so the saved file
            # includes path warnings and citation verification markers.
            research_path = plan_path.with_suffix(".research.md")
            try:
                research_path.write_text(researcher_output)
                log_message(f"Persisted annotated researcher output to {research_path}")
            except OSError as exc:
                log_message(f"Failed to persist researcher output to {research_path}: {exc}")
                print_warning(f"Could not save researcher output: {exc}")
        else:
            print_warning("Researcher failed, planner will search independently")
            researcher_output = ""
    else:
        log_message("No researcher agent configured, skipping discovery phase")

    # Planner + inspector retry loop (researcher output is fixed)
    # Attempt 1: full generation via _generate_plan_with_tui
    # Attempts 2+: targeted fix via fix_plan_with_ai (sends existing plan + errors)
    plan_content = ""
    validation_feedback = ""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if attempt == 1 or not plan_content:
            # Phase 2: Full synthesis
            print_step("Generating implementation plan...")
            success, output = _generate_plan_with_tui(
                state,
                plan_path,
                backend,
                researcher_context=researcher_output,
                local_discovery_context=local_discovery_markdown,
            )

            if not success:
                print_error("Failed to generate implementation plan")
                return False

            # Handle plan file creation
            if not plan_path.exists():
                print_info("Saving plan to file...")
                _save_plan_from_output(plan_path, state, output=output)

            if not plan_path.exists():
                print_error("Plan file was not created")
                return False
        else:
            # Phase 2b: Targeted AI fix of existing plan
            print_step(
                f"Asking AI to fix validation error(s) "
                f"(attempt {attempt}/{MAX_GENERATION_ATTEMPTS})..."
            )
            fix_success, fix_output = fix_plan_with_ai(
                state,
                plan_path,
                backend,
                existing_plan=plan_content,
                validation_feedback=validation_feedback,
                researcher_context=researcher_output,
                local_discovery_context=local_discovery_markdown,
            )

            if fix_success:
                # Handle plan mode output (save from stdout)
                use_plan_mode = backend.supports_plan_mode
                if not plan_path.exists() or use_plan_mode:
                    if fix_output.strip():
                        fixed_plan = _extract_plan_markdown(fix_output)
                        plan_path.write_text(fixed_plan)
                        log_message(f"Saved AI-fixed plan from output at {plan_path}")
                    else:
                        log_message("AI fix returned empty output; keeping previous plan on disk")
                else:
                    log_message(
                        "Backend wrote fixed plan directly (non-plan-mode); "
                        f"file exists at {plan_path}"
                    )
            else:
                log_message("AI fix attempt failed, will use previous plan for validation")

        state.plan_file = plan_path

        # Phase 3: Inspection + Self-Healing
        if state.enable_plan_validation:
            plan_content = plan_path.read_text()
            report = _validate_plan(
                plan_content,
                state,
                researcher_output=researcher_output,
                repo_root=repo_root,
            )

            # Stage A: Deterministic auto-fix (with optional FileIndex for fuzzy path correction)
            if report.has_errors:
                fixer = PlanFixer(file_index=file_index)
                fixed_content, fix_summary = fixer.fix(plan_content, report)
                if fix_summary:
                    plan_path.write_text(fixed_content)
                    plan_content = fixed_content
                    log_message(f"PlanFixer applied {len(fix_summary)} fix(es): {fix_summary}")
                    print_info(f"Auto-fixed {len(fix_summary)} validation issue(s)")
                    # Revalidate after fix
                    report = _validate_plan(
                        plan_content,
                        state,
                        researcher_output=researcher_output,
                        repo_root=repo_root,
                    )

            if report.findings:
                _display_validation_report(report)

            # Stage B: Auto-retry with AI fix (no human prompt)
            if report.has_errors:
                if attempt < MAX_GENERATION_ATTEMPTS:
                    print_info(
                        f"Validation has {report.error_count} remaining error(s), "
                        f"requesting AI fix ({attempt}/{MAX_GENERATION_ATTEMPTS - 1})..."
                    )
                    state.plan_revision_count += 1
                    validation_feedback = _format_validation_feedback(report)
                    continue  # Re-run with targeted AI fix
                else:
                    fix_attempts_made = MAX_GENERATION_ATTEMPTS - 1
                    if state.validation_strict:
                        print_error(
                            f"Plan has {report.error_count} validation error(s) "
                            f"after {fix_attempts_made} AI fix attempt(s). "
                            f"The AI could not auto-resolve these issues. "
                            f"Please review the plan manually or provide "
                            f"additional constraints."
                        )
                        return False
                    print_warning(
                        f"Proceeding to review despite {report.error_count} validation error(s)."
                    )

        break  # Success or exhausted retries — proceed to review

    # Display and user review loop (unchanged from before)
    print_success(f"Implementation plan saved to: {plan_path}")
    _display_plan_summary(plan_path)

    for _iteration in range(MAX_REVIEW_ITERATIONS):
        choice = show_plan_review_menu()

        if choice == ReviewChoice.APPROVE:
            state.current_step = 2
            return True

        elif choice == ReviewChoice.REGENERATE:
            feedback = prompt_input("What changes would you like?", default="")
            if not feedback or not feedback.strip():
                print_warning("No feedback provided. Please describe what to change.")
                continue

            state.plan_revision_count += 1
            # Intentionally reuse the initial discovery context: re-running
            # discovery mid-session is expensive, and the codebase is unlikely
            # to have changed since the initial scan.
            if replan_with_feedback(
                state,
                backend,
                feedback,
                researcher_context=researcher_output,
                local_discovery_context=local_discovery_markdown,
            ):
                _display_plan_summary(plan_path)
                # Re-run validation so user-triggered changes are checked
                if state.enable_plan_validation:
                    replan_content = plan_path.read_text()
                    replan_report = _validate_plan(
                        replan_content,
                        state,
                        researcher_output=researcher_output,
                        repo_root=repo_root,
                    )
                    if replan_report.findings:
                        _display_validation_report(replan_report)
                continue
            else:
                print_error("Failed to regenerate plan. You can retry or edit manually.")
                continue

        elif choice == ReviewChoice.EDIT:
            _edit_plan(plan_path)
            _display_plan_summary(plan_path)
            continue

        elif choice == ReviewChoice.ABORT:
            print_warning("Workflow aborted by user")
            return False
    else:
        print_warning(
            f"Maximum review iterations ({MAX_REVIEW_ITERATIONS}) reached. "
            "Please re-run the workflow."
        )
        return False


def _save_plan_from_output(plan_path: Path, state: WorkflowState, *, output: str = "") -> None:
    """Save plan from backend output if file wasn't created.

    When output is non-empty (plan mode backends output to stdout),
    sanitize and save the captured output. Falls back to a template
    when output is empty.
    """
    if output.strip():
        plan_content = _extract_plan_markdown(output)
        plan_path.write_text(plan_content)
        log_message(f"Saved plan from output at {plan_path}")
        return

    # Create a basic plan template if backend didn't create the file
    template = f"""# Implementation Plan: {state.ticket.id}

## Summary
{state.ticket.title or "Implementation task"}

## Description
{state.ticket.description or "No description was returned by the ticketing platform."}

## Implementation Steps
1. Review requirements
2. Implement changes
3. Write tests
4. Review and refactor

## Testing Strategy
- Unit tests for new functionality
- Integration tests as needed
- Manual verification

## Notes
Plan generated automatically. Please review and update as needed.
"""
    plan_path.write_text(template)
    log_message(f"Created template plan at {plan_path}")


def _display_plan_summary(plan_path: Path) -> None:
    """Display summary of the plan."""
    content = plan_path.read_text()
    lines = content.splitlines()

    # Show first 20 lines
    preview_lines = lines[:20]

    console.print()
    console.print("[bold]Plan Preview:[/bold]")
    console.print("-" * 40)
    for line in preview_lines:
        console.print(line)
    if len(lines) > len(preview_lines):
        console.print("...")
    console.print("-" * 40)
    console.print()


def _edit_plan(plan_path: Path) -> None:
    """Allow user to edit the plan file in their editor."""
    if not sys.stdin.isatty():
        print_warning("Cannot open editor: not running in a terminal")
        print_info(f"Edit the file manually: {plan_path}")
        prompt_enter("Press Enter when done editing...")
        return

    editor = os.environ.get("EDITOR", "vim")

    print_info(f"Opening plan in {editor}...")
    print_info("Save and close the editor when done.")

    try:
        editor_cmd = shlex.split(editor)
        subprocess.run([*editor_cmd, str(plan_path)], check=True)
        if plan_path.exists():
            print_success("Plan updated")
        else:
            print_warning(f"Plan file no longer exists at {plan_path}")
    except subprocess.CalledProcessError:
        print_warning("Editor exited with an error")
    except FileNotFoundError:
        print_error(f"Editor not found: {editor}")
        print_info(f"Edit the file manually: {plan_path}")
        prompt_enter("Press Enter when done editing...")


def _build_replan_prompt(
    state: WorkflowState,
    plan_path: Path,
    existing_plan: str,
    review_feedback: str,
    *,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> str:
    """Build the prompt for re-planning based on reviewer feedback.

    Args:
        state: Current workflow state.
        plan_path: Path where the plan should be saved.
        existing_plan: Current plan content (truncated for prompt size).
        review_feedback: Reviewer output explaining why replan is needed.
        researcher_context: Optional researcher output for context during replan.
        local_discovery_context: Pre-verified local discovery markdown.
    """
    # Truncate to keep prompt reasonable
    plan_excerpt = existing_plan[:_REPLAN_PLAN_EXCERPT_LIMIT]
    if len(existing_plan) > _REPLAN_PLAN_EXCERPT_LIMIT:
        plan_excerpt += "\n\n... [truncated] ..."

    feedback_excerpt = review_feedback[:_REPLAN_FEEDBACK_EXCERPT_LIMIT]
    if len(review_feedback) > _REPLAN_FEEDBACK_EXCERPT_LIMIT:
        feedback_excerpt += "\n\n... [truncated] ..."

    ticket_source_label = _SOURCE_VERIFIED if state.spec_verified else _SOURCE_UNVERIFIED

    prompt = f"""Revise the implementation plan based on reviewer feedback.

## Ticket
{ticket_source_label}
ID: {state.ticket.id}
Title: {state.ticket.title or state.ticket.branch_summary or "Not available"}
Description: {state.ticket.description or "Not available"}"""

    if not state.spec_verified:
        prompt += f"\n{_UNVERIFIED_NOTE}"

    prompt += f"""

## Current Plan (needs revision)
{plan_excerpt}

## Reviewer Feedback
The reviewer determined the current plan is flawed and needs revision:
{feedback_excerpt}

## Instructions
1. Analyze the reviewer's feedback carefully
2. Identify what needs to change in the plan
3. Write a revised implementation plan that addresses the reviewer's concerns
4. Save the revised plan to: {plan_path}

Codebase context will be retrieved automatically."""

    if state.user_constraints:
        prompt += f"""

[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]
{state.user_constraints}"""

    # Inject local discovery context (deterministic ground truth)
    if local_discovery_context:
        prompt += f"""

[SOURCE: LOCAL DISCOVERY (deterministically verified)]
{local_discovery_context}"""

    # Inject researcher context if available
    if researcher_context:
        trimmed = _truncate_researcher_context(
            researcher_context, budget=state.researcher_context_budget
        )
        prompt += f"""

[SOURCE: CODEBASE DISCOVERY (from automated research)]
{trimmed}"""

    return prompt


def replan_with_feedback(
    state: WorkflowState,
    backend: AIBackend,
    review_feedback: str,
    *,
    researcher_context: str = "",
    local_discovery_context: str = "",
) -> bool:
    """Re-generate the implementation plan based on reviewer feedback.

    Reads the existing plan, combines it with reviewer feedback, and asks
    the planner subagent to produce a revised plan.

    Args:
        state: Current workflow state.
        backend: AI backend for agent calls.
        review_feedback: The reviewer's output explaining why replan is needed.
        researcher_context: Optional researcher output for context during replan.
        local_discovery_context: Pre-verified local discovery markdown.

    Returns:
        True if plan was successfully updated, False otherwise.
    """
    print_header("Re-planning: Revising Implementation Plan")

    plan_path = state.get_plan_path()

    # Read existing plan and create backup before overwriting
    existing_plan = ""
    if plan_path.exists():
        existing_plan = plan_path.read_text()
        backup_idx = state.replan_count + state.plan_revision_count
        backup_path = plan_path.with_suffix(f".pre-replan-{backup_idx}.md")
        backup_path.write_text(existing_plan)
        log_message(f"Backed up previous plan to {backup_path}")

    # Build replan prompt
    use_plan_mode = backend.supports_plan_mode
    prompt = _build_replan_prompt(
        state,
        plan_path,
        existing_plan,
        review_feedback,
        researcher_context=researcher_context,
        local_discovery_context=local_discovery_context,
    )

    if use_plan_mode:
        prompt += """

Output the complete revised implementation plan in Markdown format to stdout.
Do not attempt to create or write any files."""

    # Run the planner subagent
    # dont_save_session=True: Replan attempts are transient and should not
    # pollute the session history, which is reserved for the main plan run.
    print_step("Generating revised implementation plan...")
    try:
        success, output = backend.run_with_callback(
            prompt,
            subagent=state.subagent_names["planner"],
            output_callback=noop_output_callback,
            dont_save_session=True,
            plan_mode=use_plan_mode,
        )
    except Exception as e:
        print_error(f"Re-planning failed: {e}")
        return False

    if not success:
        print_error("Re-planning agent returned failure")
        return False

    # Handle plan mode output (save from stdout)
    if not plan_path.exists() or use_plan_mode:
        if output.strip():
            plan_content = _extract_plan_markdown(output)
            plan_path.write_text(plan_content)
            log_message(f"Saved revised plan from output at {plan_path}")

    if plan_path.exists():
        print_success(f"Revised plan saved to: {plan_path}")
        state.plan_file = plan_path
        _display_plan_summary(plan_path)
        return True
    else:
        print_error("Revised plan file was not created")
        return False


__all__ = [
    "replan_with_feedback",
    "step_1_create_plan",
    "build_fix_prompt",
    "fix_plan_with_ai",
]
