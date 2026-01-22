"""
Task memory system for cross-task learning.

This module implements a memory system that captures patterns and learnings
from completed tasks, allowing later tasks to benefit from earlier work
WITHOUT keeping full raw chat history (avoiding context pollution).
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from spec.utils.logging import log_message
from spec.workflow.state import WorkflowState
from spec.workflow.tasks import Task


@dataclass
class TaskMemory:
    """Captures learnings from a completed task."""
    task_name: str
    files_modified: list[str] = field(default_factory=list)
    patterns_used: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Format as markdown for prompt context."""
        parts = [f"### {self.task_name}"]

        if self.files_modified:
            parts.append(f"**Files:** {', '.join(self.files_modified)}")

        if self.patterns_used:
            parts.append("**Patterns:**")
            for pattern in self.patterns_used:
                parts.append(f"- {pattern}")

        if self.key_decisions:
            parts.append("**Key Decisions:**")
            for decision in self.key_decisions:
                parts.append(f"- {decision}")

        return "\n".join(parts)


def capture_task_memory(task: Task, state: WorkflowState) -> TaskMemory:
    """Capture learnings from a completed task.

    This extracts patterns and decisions from the task without keeping
    the full conversation history, avoiding context pollution.

    Args:
        task: Completed task
        state: Current workflow state

    Returns:
        TaskMemory with captured learnings
    """
    log_message(f"Capturing task memory for: {task.name}")

    # Get modified files from git
    modified_files = _get_modified_files()

    # Analyze changes to identify patterns
    patterns = _identify_patterns_in_changes(modified_files)

    # Extract test commands if this was a test task
    test_commands = _extract_test_commands(task, modified_files)

    memory = TaskMemory(
        task_name=task.name,
        files_modified=modified_files,
        patterns_used=patterns,
        key_decisions=[],  # Could be extracted from commit message
        test_commands=test_commands
    )

    # Add to state
    if not hasattr(state, 'task_memories'):
        state.task_memories = []
    state.task_memories.append(memory)

    log_message(f"Captured {len(patterns)} patterns from task")

    return memory


def _get_modified_files() -> list[str]:
    """Get list of modified files from git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True,
            text=True,
            check=True
        )
        files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
        return files
    except subprocess.CalledProcessError:
        return []


def _identify_patterns_in_changes(files: list[str]) -> list[str]:
    """Identify patterns in the changed files.

    Args:
        files: List of modified file paths

    Returns:
        List of identified patterns
    """
    patterns = []

    # Analyze file types and locations
    file_types = {Path(f).suffix for f in files}
    directories = {Path(f).parent for f in files}

    # Identify common patterns
    if '.py' in file_types:
        patterns.append("Python implementation")

        # Check for test files
        if any('test' in f for f in files):
            patterns.append("Added Python tests")

    if '.ts' in file_types or '.tsx' in file_types:
        patterns.append("TypeScript implementation")

        if any('test' in f or 'spec' in f for f in files):
            patterns.append("Added TypeScript tests")

    # Check for API patterns
    if any('api' in str(d).lower() for d in directories):
        patterns.append("API endpoint implementation")

    # Check for database patterns
    if any('model' in str(d).lower() or 'schema' in str(d).lower() for d in directories):
        patterns.append("Database schema/model")

    # Check for UI patterns
    if any('component' in str(d).lower() or 'ui' in str(d).lower() for d in directories):
        patterns.append("UI component")

    # Analyze actual changes for more patterns
    try:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            capture_output=True,
            text=True,
            check=True
        )
        diff_content = result.stdout

        # Look for common patterns in diff
        if 'async def' in diff_content or 'async function' in diff_content:
            patterns.append("Async/await pattern")

        if 'try:' in diff_content or 'try {' in diff_content:
            patterns.append("Error handling with try/catch")

        if '@dataclass' in diff_content:
            patterns.append("Dataclass pattern")

        if 'pytest' in diff_content or 'describe(' in diff_content:
            patterns.append("Test suite structure")

    except subprocess.CalledProcessError:
        pass

    return patterns


def _extract_test_commands(task: Task, files: list[str]) -> list[str]:
    """Extract test commands from task or modified files.

    Args:
        task: The task
        files: Modified files

    Returns:
        List of test commands
    """
    commands = []

    # Check if this is a test task
    if 'test' in task.name.lower():
        # Look for test files
        test_files = [f for f in files if 'test' in f or 'spec' in f]

        for test_file in test_files:
            if test_file.endswith('.py'):
                commands.append(f"pytest {test_file}")
            elif test_file.endswith('.ts') or test_file.endswith('.tsx'):
                commands.append(f"npm test {test_file}")

    return commands


def find_related_task_memories(
    task: Task,
    memories: list[TaskMemory]
) -> list[TaskMemory]:
    """Find task memories relevant to the current task.

    Args:
        task: Current task
        memories: All captured task memories

    Returns:
        List of relevant task memories
    """
    if not memories:
        return []

    related = []
    task_name_lower = task.name.lower()

    # Find memories with similar task names
    for memory in memories:
        memory_name_lower = memory.task_name.lower()

        # Check for keyword overlap
        task_keywords = set(re.findall(r'\w+', task_name_lower))
        memory_keywords = set(re.findall(r'\w+', memory_name_lower))

        overlap = task_keywords & memory_keywords
        if len(overlap) >= 2:  # At least 2 common keywords
            related.append(memory)
            continue

    return related


def build_pattern_context(task: Task, state: WorkflowState) -> str:
    """Build context from previous task patterns.

    This provides learned patterns to the next task WITHOUT including
    the full raw conversation history, avoiding context pollution.

    Args:
        task: Current task
        state: Workflow state with task memories

    Returns:
        Formatted pattern context for prompt
    """
    if not hasattr(state, 'task_memories') or not state.task_memories:
        return ""

    # Find related memories
    related = find_related_task_memories(task, state.task_memories)

    if not related:
        # Even if no related memories, provide summary of all patterns
        if len(state.task_memories) > 0:
            all_patterns = set()
            for memory in state.task_memories:
                all_patterns.update(memory.patterns_used)

            if all_patterns:
                return f"""## Established Patterns

The following patterns have been used in previous tasks:
{chr(10).join(f"- {p}" for p in sorted(all_patterns))}

Follow these patterns for consistency."""
        return ""

    context_parts = ["## Patterns from Previous Tasks\n"]
    context_parts.append("The following patterns were established in earlier tasks:\n")

    for memory in related:
        context_parts.append(memory.to_markdown())
        context_parts.append("")  # Blank line

    context_parts.append("Follow these established patterns for consistency.")

    return "\n".join(context_parts)


__all__ = [
    "TaskMemory",
    "capture_task_memory",
    "find_related_task_memories",
    "build_pattern_context",
]

