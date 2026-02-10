"""Prompt templates and formatting for Step 3 execution.

This module provides utilities for building prompts used during
the task execution and post-implementation phases.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingot.workflow.tasks import Task


def build_task_prompt(
    task: Task, plan_path: Path, *, is_parallel: bool = False, user_context: str = ""
) -> str:
    """Build a minimal prompt for task execution.

    Passes a plan path reference rather than the full plan content to:
    - Reduce token usage and context window pressure
    - Let the agent retrieve only relevant sections via codebase-retrieval
    - Avoid prompt bloat in parallel execution scenarios

    Args:
        task: Task to execute
        plan_path: Path to the implementation plan file
        is_parallel: Whether this task runs in parallel with others
        user_context: Optional additional context provided by the user

    Returns:
        Minimal prompt string with task context
    """
    parallel_mode = "YES" if is_parallel else "NO"

    # Base prompt with task name and parallel mode
    prompt = f"""Execute task: {task.name}

Parallel mode: {parallel_mode}"""

    # Add plan reference if file exists
    if plan_path.exists():
        prompt += f"""

Implementation plan: {plan_path}
Use codebase-retrieval to read relevant sections of the plan as needed."""
    else:
        prompt += """

Use codebase-retrieval to understand existing patterns before making changes."""

    # Add target files if task has them
    if task.target_files:
        files_list = "\n".join(f"- {f}" for f in task.target_files)
        prompt += f"""

Target files for this task:
{files_list}
Focus your changes on these files."""

    # Add user-provided context if available
    if user_context and user_context.strip():
        prompt += f"""

Additional Context:
{user_context.strip()}"""

    # Add critical constraints reminder
    prompt += """

Do NOT commit, git add, or push any changes."""

    return prompt


# Test prompt template for post-implementation verification
POST_IMPLEMENTATION_TEST_PROMPT = """Identify and run the tests that are relevant to the code changes made in this run.

## Step 1: Identify Changed Production Code
- Run `git diff --name-only` and `git status --porcelain` to list all files changed in this run.
- Separate the changed files into two categories:
  a) **Test files**: files in directories like `test/`, `tests/`, `__tests__/`, or matching patterns like `*.spec.*`, `*_test.*`, `test_*.*`
  b) **Production/source files**: all other changed files (excluding test paths above)

## Step 2: Determine Relevant Tests to Run
Find the minimal, most targeted set of tests that cover the changes:
- **If test files were modified/added**: include those tests.
- **If production/source files were modified/added**: use codebase-retrieval and repository conventions to find tests that cover those files. Look for:
  - Tests located in the same module/package area as the changed source files
  - Tests named similarly to the changed files (e.g., `foo.py` → `test_foo.py`, `foo_test.py`, `foo.spec.ts`)
  - Tests referenced by existing docs, scripts, or test configuration in the repo
- Prefer the smallest targeted set. If the repo supports running tests by file, class, or package, use that to scope execution.

## Step 3: Transparency Before Execution
Before running any tests:
- Print the exact command(s) you plan to run.
- Briefly explain how these tests were selected (e.g., "These tests correspond to module X which was changed" or "These are the modified test files").

## Step 4: Execute Tests
Run the identified tests and clearly report success or failure.

## Critical Constraints
- Do NOT commit any changes
- Do NOT push any changes
- Do NOT run the entire project test suite by default
- Only expand the test scope if a targeted run is not possible in this repo

## Fallback Behavior
If you cannot reliably map changed source files to specific tests AND cannot run targeted tests in this repo:
1. Explain why targeted test selection is not possible.
2. Propose 1-2 broader-but-still-reasonable commands (e.g., module-level tests, package-level tests).
3. Ask the user for confirmation before running them.
4. Do NOT silently fall back to "run everything".

If NO production files were changed AND NO test files were changed, report "No code changes detected that require testing" and STOP."""


__all__ = [
    "build_task_prompt",
    "POST_IMPLEMENTATION_TEST_PROMPT",
]
