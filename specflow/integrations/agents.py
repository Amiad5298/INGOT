"""Subagent file management for SPECFLOW.

This module provides utilities for managing SPECFLOW subagent definition files
in the `.augment/agents/` directory.

Supports versioned agent files with automatic update detection:
- Adds specflow_version and specflow_content_hash to frontmatter
- Detects when internal templates are newer than on-disk files
- Respects user customizations (won't overwrite modified files)
"""

import hashlib
from collections.abc import Iterator
from pathlib import Path

from specflow import __version__
from specflow.integrations.auggie import (
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
    version_gte,
)
from specflow.integrations.git import find_repo_root
from specflow.utils.console import print_info, print_step, print_success, print_warning
from specflow.utils.logging import log_message

# --- Frontmatter and Hash Utilities ---


def normalize_content(content: str) -> str:
    """Normalize content for consistent hashing across platforms.

    Handles:
    - CRLF vs LF line endings (Windows vs Unix)
    - Trailing whitespace on lines
    - Trailing newlines at end of file

    Args:
        content: Raw content string

    Returns:
        Normalized content with LF line endings and trimmed whitespace
    """
    # Normalize line endings to LF
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in normalized.split("\n")]
    # Join and strip trailing newlines, then add single trailing newline
    return "\n".join(lines).rstrip("\n") + "\n"


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of normalized content.

    Args:
        content: Content to hash (will be normalized first)

    Returns:
        Hex-encoded SHA-256 hash (first 16 chars for brevity)
    """
    normalized = normalize_content(content)
    full_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    # Use first 16 chars - sufficient for collision avoidance in this context
    return full_hash[:16]


def parse_agent_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from agent file content.

    Expects format:
    ---
    key: value
    key2: value2
    ---
    body content...

    Args:
        content: Full file content

    Returns:
        Dictionary of frontmatter key-value pairs (empty if no frontmatter)
    """
    content = content.strip()
    if not content.startswith("---"):
        return {}

    # Find closing ---
    lines = content.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}

    # Parse simple YAML (key: value pairs only)
    frontmatter = {}
    for line in lines[1:end_idx]:
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()

    return frontmatter


def extract_agent_body(content: str) -> str:
    """Extract body content after frontmatter.

    Args:
        content: Full file content with frontmatter

    Returns:
        Body content (everything after closing ---)
    """
    content = content.strip()
    if not content.startswith("---"):
        return content

    # Find closing ---
    lines = content.split("\n")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            # Return everything after the closing ---
            body = "\n".join(lines[i + 1 :])
            return body.strip()

    # No closing --- found, return original
    return content


def build_agent_frontmatter(
    name: str,
    description: str,
    model: str,
    color: str,
    body_hash: str,
) -> str:
    """Build YAML frontmatter string with version metadata.

    Args:
        name: Agent name
        description: Agent description
        model: Model identifier
        color: Display color
        body_hash: Hash of the body content

    Returns:
        Formatted frontmatter string including --- delimiters
    """
    return f"""---
name: {name}
description: {description}
model: {model}
color: {color}
spec_version: {__version__}
spec_content_hash: {body_hash}
---"""


def is_agent_customized(existing_content: str, expected_body: str) -> bool:
    """Check if user has modified the agent body from the default.

    Compares the normalized body content against the expected default.

    Args:
        existing_content: Full content of the existing agent file
        expected_body: The default body content we expect

    Returns:
        True if user has customized the file, False if it matches default
    """
    existing_body = extract_agent_body(existing_content)
    existing_hash = compute_content_hash(existing_body)
    expected_hash = compute_content_hash(expected_body)
    return existing_hash != expected_hash


# --- Agent Metadata and Body Definitions ---
# Separated to allow dynamic frontmatter generation with versioning

# Agent metadata: name, description, model, color
AGENT_METADATA = {
    SPECFLOW_AGENT_PLANNER: {
        "name": "spec-planner",
        "description": "SPECFLOW workflow planner - creates implementation plans from requirements",
        "model": "claude-sonnet-4-5",
        "color": "blue",
    },
    SPECFLOW_AGENT_TASKLIST: {
        "name": "spec-tasklist",
        "description": "SPECFLOW workflow task generator - creates executable task lists",
        "model": "claude-sonnet-4-5",
        "color": "cyan",
    },
    SPECFLOW_AGENT_TASKLIST_REFINER: {
        "name": "spec-tasklist-refiner",
        "description": "Post-processor that extracts test-related work from FUNDAMENTAL to INDEPENDENT",
        "model": "claude-sonnet-4-5",
        "color": "yellow",
    },
    SPECFLOW_AGENT_IMPLEMENTER: {
        "name": "spec-implementer",
        "description": "SPECFLOW workflow implementer - executes individual tasks",
        "model": "claude-sonnet-4-5",
        "color": "green",
    },
    SPECFLOW_AGENT_REVIEWER: {
        "name": "spec-reviewer",
        "description": "SPECFLOW workflow reviewer - validates completed tasks",
        "model": "claude-sonnet-4-5",
        "color": "purple",
    },
}

# Agent body content (prompts) - without frontmatter
AGENT_BODIES = {
    SPECFLOW_AGENT_PLANNER: '''
You are an implementation planning AI assistant working within the SPEC workflow.
Your role is to analyze requirements and create a comprehensive implementation plan.

## Your Task

Create a detailed implementation plan based on the provided ticket/requirements.
The plan will be used to generate an executable task list for AI agents.

## Analysis Process

1. **Understand Requirements**: Parse the ticket description, acceptance criteria, and any linked context
2. **Explore Codebase**: Use context retrieval to understand existing patterns, architecture, and conventions
3. **Identify Components**: List all files, modules, and systems that need modification
4. **Consider Edge Cases**: Think about error handling, validation, and boundary conditions
5. **Plan Testing**: Include testing strategy alongside implementation

## Output Format

Create a markdown document and save it to the specified path with these sections:

### Summary
Brief summary of what will be implemented and why.

### Technical Approach
Architecture decisions, patterns to follow, and how the solution fits into the existing codebase.

### Implementation Steps
Numbered, ordered steps to implement the feature. Be specific about which files to create or modify.

### Testing Strategy
Types of tests needed and key scenarios to cover.

### Potential Risks or Considerations
Challenges, edge cases, or things to watch out for during implementation.

### Out of Scope
What this implementation explicitly does NOT include.

## Guidelines

- Be specific and actionable - vague plans lead to poor task lists
- Reference existing code patterns in the codebase
- Consider both happy path and error scenarios
- Keep the plan focused on the ticket scope - don't expand unnecessarily
- Include estimated complexity/effort hints where helpful
- Use codebase-retrieval to understand the current architecture before planning
''',
    SPECFLOW_AGENT_TASKLIST: '''
You are a task list generation AI assistant working within the SPEC workflow.
Your job is to convert an implementation plan into an executable task list optimized for AI agents:
- FUNDAMENTAL tasks: sequential (dependency-enabling)
- INDEPENDENT tasks: parallel (dependency-consuming)

# NON-NEGOTIABLE HARD GATES (FAIL = REWRITE BEFORE OUTPUT)

## GATE 1 - ZERO TESTS IN FUNDAMENTAL (ABSOLUTE)
FUNDAMENTAL tasks must contain **NO test-related work**. This is a strict ban, not "only comprehensive".

**Definition: "test-related" includes ANY of:**
- Framework tokens: `JUnit`, `Mockito`, `Assert`, `@Test`
- File indicators: `*Test.java`, `/src/test/`, `src/test`, `tests/`, `test_*.py`
- Phrases: "verify with tests", "add tests", "write tests", "cover success/error cases"
- The word `test` (case-insensitive) as a **distinct word/token** (e.g., "unit test", "run test")

**Word Boundary Rule:** The word "test" must not appear as a standalone word in FUNDAMENTAL sections.
If "test" appears as a distinct token: STOP, extract that line into an INDEPENDENT task (group: testing), then re-check.

## GATE 2 - ALL AUTOMATED TESTS ARE INDEPENDENT (group: testing only)
All automated tests (unit/integration/fixtures) must be INDEPENDENT tasks with:
`<!-- category: independent, group: testing -->`

Tests always use exactly: `group: testing`.

## GATE 3 - EVERY TASK MUST DECLARE FILES (MANDATORY FORMAT)
Every single task bullet (`- [ ]`) **MUST** be preceded immediately by exactly one files comment:

`<!-- files: path/a, path/b -->`

No task may omit it. No extra lines between the files comment and the task bullet.

### How to Extract File Paths (MANDATORY)
1. **Scan the Implementation Plan** for file references. Look for:
   - Explicit file headers: `### File: path/to/file.py`
   - Inline references: "in `SomeClass.java`", "modify `config.yaml`"
   - Step descriptions: "Create UpdateMeteringLogLinkResponseModel.java DTO"
2. **Map each task** to the files it will create or modify based on the plan's description.
3. **Use actual paths** from the plan - do NOT invent or guess paths.

### Fail-Loudly Rule
If you cannot determine the files for a task:
- Use `<!-- files: UNRESOLVED - [reason] -->`
- This triggers a validation failure and forces manual review.
- Do NOT omit the files comment entirely.

### Enforcement (STOP and Verify)
Before finalizing output: scan every `- [ ]` line.
If ANY task lacks an immediately preceding `<!-- files: ... -->` comment: **STOP. Add the missing file comment. Then continue.**

## GATE 4 - INDEPENDENT TASKS MUST HAVE DISJOINT FILE SETS
Any two INDEPENDENT tasks must not touch the same file.
If a shared file would be edited by more than one INDEPENDENT task, you MUST do ONE of:
1) Create a FUNDAMENTAL task that performs ALL edits to that shared file, then remove it from INDEPENDENT tasks.
2) Merge the conflicting INDEPENDENT tasks into one task (only if it stays "one session sized").

# Allowed INDEPENDENT groups (strict)
INDEPENDENT `group:` must be one of: `testing`, `implementation`, `docs`, `ui`

# Task Sizing
- Target 3-8 total tasks for a typical feature
- Each task must be completable in a single agent session
- FUNDAMENTAL should be minimal (core enabling steps only)
- INDEPENDENT should be the majority (wrappers, tests, docs)

# Output Format

**IMPORTANT:** Output ONLY the task list as plain markdown text. Do NOT use any task management tools.

```markdown
# Task List: [TICKET-ID]

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: 1 -->
<!-- files: path/to/file1.py, path/to/file2.py -->
- [ ] [First foundational task]

<!-- category: fundamental, order: 2 -->
<!-- files: path/to/file3.py -->
- [ ] [Second foundational task that depends on first]

## Independent Tasks (Parallel)

<!-- category: independent, group: implementation -->
<!-- files: path/to/feature.py -->
- [ ] [Feature task A - can run in parallel]

<!-- category: independent, group: testing -->
<!-- files: tests/test_feature.py -->
- [ ] Unit Tests: [Component name]
```

## Final Validation Checklist (must pass before output)

- Every task has an immediate `<!-- files: ... -->` comment
- FUNDAMENTAL sections contain NO occurrence of the word "test" as a distinct token
- INDEPENDENT tasks have disjoint file sets (no overlaps)
- INDEPENDENT `group:` values are ONLY one of: `testing`, `implementation`, `docs`, `ui`

If any check fails, rewrite the output until it passes.
''',
    SPECFLOW_AGENT_TASKLIST_REFINER: '''
You are a task list post-processor for the SPEC workflow.

# Your Single Job
Extract any test-related work from FUNDAMENTAL tasks and move them to INDEPENDENT tasks with `group: testing`.

# Input
You receive a task list with FUNDAMENTAL and INDEPENDENT sections.

# What to Look For
Scan FUNDAMENTAL tasks for ANY test-related content:
- Mentions of writing/adding/updating tests
- Test file references (e.g., `*Test.java`, `*_test.py`, `*_test.go`, `*.test.ts`, `*.spec.js`)
- Test directories (e.g., `src/test/`, `tests/`, `__tests__/`, `spec/`)
- Test frameworks (JUnit, pytest, Jest, Mocha, RSpec, Go testing, etc.)
- Phrases like "verify with tests", "add unit tests", "write integration tests"
- The word "test" as a distinct token in the context of automated testing

# How to Extract
For each test-related line found in a FUNDAMENTAL task:
1. Remove that line/bullet from the FUNDAMENTAL task
2. Create a new INDEPENDENT task with `<!-- category: independent, group: testing -->`
3. The new task should reference which component it tests

# Output Format
Output ONLY the complete refined task list in markdown. Keep the exact same format:

```markdown
# Task List: [TICKET-ID]

## Fundamental Tasks (Sequential)

<!-- category: fundamental, order: N -->
<!-- files: ... -->
- [ ] **Task name**
  - Implementation detail 1
  - Implementation detail 2
  (NO test-related bullets here)

## Independent Tasks (Parallel)

<!-- category: independent, group: implementation -->
<!-- files: ... -->
- [ ] ...

<!-- category: independent, group: testing -->
<!-- files: ... -->
- [ ] **Unit Tests: ComponentName**
  - Test success scenarios
  - Test error handling
```

# Rules
1. Preserve ALL non-test content exactly as-is
2. Preserve file metadata comments (`<!-- files: ... -->`)
3. Preserve order numbers for fundamental tasks
4. If a FUNDAMENTAL task becomes empty after extraction, remove it entirely
5. New testing tasks should have descriptive names like "Unit Tests: DasService" or "Integration Tests: API Layer"
6. Group related test extractions into single tasks when they test the same component
7. Do NOT invent new implementation work - only move existing test-related work
8. Do NOT summarize or rephrase implementation tasks. Copy them verbatim.
9. If a task has a files comment containing both implementation and test files, you must SPLIT the file list correctly between the resulting tasks.

# Example Transformation

BEFORE (in FUNDAMENTAL):
```
<!-- category: fundamental, order: 2 -->
<!-- files: src/main/java/DasService.java, src/test/java/DasServiceTest.java -->
- [ ] **Implement DAS adapter layer**
  - Create UpdateMeteringLogLinkResponseModel.java DTO
  - Add converter methods to DasResponseConverter.java
  - Write unit tests in DasServiceImplTest.java
  - Write unit tests in DasResponseConverterTest.java
```

AFTER:
```
<!-- category: fundamental, order: 2 -->
<!-- files: src/main/java/DasService.java -->
- [ ] **Implement DAS adapter layer**
  - Create UpdateMeteringLogLinkResponseModel.java DTO
  - Add converter methods to DasResponseConverter.java

<!-- category: independent, group: testing -->
<!-- files: src/test/java/DasServiceImplTest.java, src/test/java/DasResponseConverterTest.java -->
- [ ] **Unit Tests: DAS adapter layer**
  - Write unit tests in DasServiceImplTest.java
  - Write unit tests in DasResponseConverterTest.java
```

Output ONLY the refined task list markdown. No explanations.
''',
    SPECFLOW_AGENT_IMPLEMENTER: '''
You are a task execution AI assistant working within the SPEC workflow.
Your role is to complete ONE specific implementation task.

## Your Task

Execute the single task provided. You have access to the full implementation plan for context,
but focus ONLY on completing the specific task assigned.

## Execution Guidelines

### Do
- Complete the specific task fully and correctly
- Follow existing code patterns and conventions in the codebase
- Write tests alongside implementation code
- Handle error cases appropriately
- Use codebase-retrieval to understand existing patterns before making changes
- Read the implementation plan for context on the overall approach

### Do NOT
- Make commits (SPEC handles checkpoint commits)
- Run `git add`, `git commit`, or `git push`
- Stage any changes
- Expand scope beyond the assigned task
- Modify files unrelated to your task
- Start work on other tasks from the list
- Refactor unrelated code

## Quality Standards

1. **Correctness**: Code must work as intended
2. **Consistency**: Follow existing patterns in the codebase
3. **Completeness**: Include error handling and edge cases
4. **Testability**: Write or update tests for new functionality

## Parallel Execution Mode

When running in parallel with other tasks:
- You are one of multiple AI agents working concurrently
- Each agent works on different files - do NOT touch files outside your task scope
- Staging/committing will be done after all tasks complete
- Focus only on your specific task

## Output

When complete, briefly summarize:
- What was implemented
- Files created/modified
- Tests added
- Any issues encountered or decisions made

Do not output the full file contents unless specifically helpful.
''',
    SPECFLOW_AGENT_REVIEWER: '''
You are a task validation AI assistant working within the SPEC workflow.
Your role is to quickly verify that a completed task meets requirements.

## Your Task

Review the changes made for a specific task and validate:

1. **Completeness**: Does the implementation address the task requirements?
2. **Correctness**: Are there obvious bugs or logic errors?
3. **Tests**: Were appropriate tests added?
4. **Scope**: Did the changes stay within task scope?

## Review Focus

### Check For
- Missing error handling
- Incomplete implementations (TODOs, placeholder code)
- Tests that don't actually test the functionality
- Unintended changes to other files
- Breaking changes to existing functionality
- Security issues (hardcoded secrets, SQL injection, etc.)

### Do NOT Check
- Style preferences (leave to linters)
- Minor refactoring opportunities
- Performance optimizations (unless critical)
- Naming bikeshedding

## Review Process

1. Use `git diff` or `git status` to see what files were changed
2. Read the implementation plan to understand the expected changes
3. Verify the task requirements were met
4. Check that tests cover the new functionality
5. Look for obvious issues or missing pieces

## Output Format

```
## Task Review: [Task Name]

**Status**: PASS | NEEDS_ATTENTION

**Summary**: [One sentence summary]

**Files Changed**:
- file1.py (modified)
- file2.py (created)

**Issues** (if any):
- Issue 1
- Issue 2

**Recommendation**: [Proceed | Fix before continuing]
```

Keep reviews quick and focused - this is a sanity check, not a full code review.

## Guidelines

- Be pragmatic, not pedantic
- Focus on correctness and completeness
- Trust the implementing agent made reasonable decisions
- Only flag genuine problems, not style preferences
- A quick pass is better than no review
''',
}


def get_agent_body(agent_name: str) -> str:
    """Get the body content for an agent (without frontmatter).

    Args:
        agent_name: Agent identifier (e.g., SPECFLOW_AGENT_PLANNER)

    Returns:
        Body content string, stripped of leading/trailing whitespace
    """
    return AGENT_BODIES.get(agent_name, "").strip()


def generate_agent_content(agent_name: str) -> str:
    """Generate full agent file content with versioned frontmatter.

    Combines metadata and body with spec_version and spec_content_hash
    in the frontmatter for update detection.

    Args:
        agent_name: Agent identifier (e.g., SPECFLOW_AGENT_PLANNER)

    Returns:
        Complete agent file content ready to write to disk
    """
    if agent_name not in AGENT_METADATA or agent_name not in AGENT_BODIES:
        raise ValueError(f"Unknown agent: {agent_name}")

    meta = AGENT_METADATA[agent_name]
    body = get_agent_body(agent_name)
    body_hash = compute_content_hash(body)

    frontmatter = build_agent_frontmatter(
        name=meta["name"],
        description=meta["description"],
        model=meta["model"],
        color=meta["color"],
        body_hash=body_hash,
    )

    return f"{frontmatter}\n\n{body}\n"


def get_all_agent_names() -> list[str]:
    """Get list of all agent identifiers.

    Returns:
        List of agent name constants
    """
    return list(AGENT_METADATA.keys())


# Compatibility alias - generates content dynamically with versioning
# This allows existing code using AGENT_DEFINITIONS to continue working
class _AgentDefinitionsProxy:
    """Proxy that generates versioned agent content on access."""

    def __iter__(self) -> Iterator[str]:
        return iter(AGENT_METADATA.keys())

    def __getitem__(self, key: str) -> str:
        return generate_agent_content(key)

    def __contains__(self, key: str) -> bool:
        return key in AGENT_METADATA

    def keys(self) -> Iterator[str]:
        return iter(AGENT_METADATA.keys())

    def items(self) -> Iterator[tuple[str, str]]:
        for key in AGENT_METADATA:
            yield key, generate_agent_content(key)


AGENT_DEFINITIONS = _AgentDefinitionsProxy()


def get_agents_dir() -> Path:
    """Get the path to the .augment/agents directory.

    Returns:
        Path to the agents directory
    """
    return Path(".augment/agents")


def _check_agent_needs_update(agent_path: Path, agent_name: str) -> tuple[bool, bool]:
    """Check if an existing agent file needs to be updated.

    Args:
        agent_path: Path to existing agent file
        agent_name: Agent identifier

    Returns:
        Tuple of (needs_update, is_customized)
        - needs_update: True if our version is newer than the file's version
        - is_customized: True if user has modified the file body
    """
    try:
        existing_content = agent_path.read_text()
    except Exception:
        return True, False  # Can't read, treat as needs update

    existing_meta = parse_agent_frontmatter(existing_content)
    existing_version = existing_meta.get("spec_version", "0.0.0")

    # Check if current SPEC version is newer
    needs_update = not version_gte(existing_version, __version__)

    if not needs_update:
        return False, False

    # Check if user customized the file
    expected_body = get_agent_body(agent_name)
    is_customized = is_agent_customized(existing_content, expected_body)

    return needs_update, is_customized


def _create_agent_file(agent_path: Path, agent_name: str, quiet: bool = False) -> bool:
    """Create a new agent file with versioned content.

    Args:
        agent_path: Path to create
        agent_name: Agent identifier
        quiet: Suppress output

    Returns:
        True if successful
    """
    try:
        agent_content = generate_agent_content(agent_name)
        agent_path.write_text(agent_content)
        if not quiet:
            print_info(f"Created agent file: {agent_path}")
        log_message(f"Created agent file: {agent_path}")
        return True
    except Exception as e:
        print_warning(f"Failed to create agent file {agent_path}: {e}")
        log_message(f"Failed to create agent file {agent_path}: {e}")
        return False


def _update_agent_file(agent_path: Path, agent_name: str, quiet: bool = False) -> bool:
    """Update an existing agent file with new versioned content.

    Args:
        agent_path: Path to update
        agent_name: Agent identifier
        quiet: Suppress output

    Returns:
        True if successful
    """
    try:
        agent_content = generate_agent_content(agent_name)
        agent_path.write_text(agent_content)
        if not quiet:
            print_info(f"Updated agent file: {agent_path}")
        log_message(f"Updated agent file to version {__version__}: {agent_path}")
        return True
    except Exception as e:
        print_warning(f"Failed to update agent file {agent_path}: {e}")
        log_message(f"Failed to update agent file {agent_path}: {e}")
        return False


# --- Gitignore Management ---

# Patterns that SPECFLOW requires in the target project's .gitignore
# Note: We do NOT ignore specs/ because plan and tasklist .md files should be visible to users
# Only runtime artifacts (.specflow/ for logs/state, *.log files) are ignored
SPECFLOW_GITIGNORE_PATTERNS = [
    ".specflow/",
    "*.log",
]

# Comment marker to identify SPECFLOW-managed section
SPECFLOW_GITIGNORE_MARKER = "# SPECFLOW - Run logs and temporary files"


def _check_gitignore_has_pattern(content: str, pattern: str) -> bool:
    """Check if a .gitignore file contains a specific pattern.

    Handles comments and whitespace. Matches the pattern exactly
    (not as a substring of another pattern).

    Args:
        content: Content of the .gitignore file
        pattern: Pattern to search for (e.g., ".specflow/", "*.log")

    Returns:
        True if the pattern is already in the file
    """
    for line in content.split("\n"):
        # Strip whitespace and skip comments
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if stripped == pattern:
                return True
    return False


def ensure_gitignore_configured(quiet: bool = False) -> bool:
    """Ensure the target project's .gitignore has SPECFLOW patterns.

    Checks for required patterns (.specflow/, *.log) and appends them
    if missing. Adds patterns in a clearly marked SPECFLOW section.

    This function finds the git repository root and updates the .gitignore
    there, ensuring the correct project is targeted regardless of the
    current working directory.

    This is idempotent - running multiple times won't duplicate entries.

    Args:
        quiet: If True, suppress informational messages

    Returns:
        True if .gitignore is properly configured (or was updated successfully)
    """
    # Find the git repository root to ensure we update the correct .gitignore
    repo_root = find_repo_root()
    if repo_root is None:
        # Not in a git repository - fall back to current directory
        gitignore_path = Path(".gitignore")
        log_message("Not in a git repository, using current directory for .gitignore")
    else:
        gitignore_path = repo_root / ".gitignore"
        log_message(f"Found git repository root: {repo_root}")

    # Read existing content (or empty if file doesn't exist)
    if gitignore_path.exists():
        try:
            existing_content = gitignore_path.read_text()
        except Exception as e:
            if not quiet:
                print_warning(f"Failed to read .gitignore: {e}")
            log_message(f"Failed to read .gitignore: {e}")
            return False
    else:
        existing_content = ""

    # Find missing patterns
    missing_patterns = [
        pattern for pattern in SPECFLOW_GITIGNORE_PATTERNS
        if not _check_gitignore_has_pattern(existing_content, pattern)
    ]

    if not missing_patterns:
        log_message(".gitignore already has all required SPECFLOW patterns")
        return True

    # Build the section to append
    lines_to_add = []

    # Add blank line separator if file has content and doesn't end with newlines
    if existing_content and not existing_content.endswith("\n\n"):
        if existing_content.endswith("\n"):
            lines_to_add.append("")
        else:
            lines_to_add.extend(["", ""])

    # Check if we already have the SPECFLOW marker
    has_marker = SPECFLOW_GITIGNORE_MARKER in existing_content

    if not has_marker:
        lines_to_add.append(SPECFLOW_GITIGNORE_MARKER)

    lines_to_add.extend(missing_patterns)
    lines_to_add.append("")  # Trailing newline

    # Append to file
    try:
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines_to_add))

        if not quiet:
            pattern_list = ", ".join(missing_patterns)
            print_info(f"Updated .gitignore with SPECFLOW patterns: {pattern_list}")
        log_message(f"Added patterns to .gitignore: {missing_patterns}")
        return True

    except Exception as e:
        if not quiet:
            print_warning(f"Failed to update .gitignore: {e}")
        log_message(f"Failed to update .gitignore: {e}")
        return False


def ensure_agents_installed(quiet: bool = False) -> bool:
    """Ensure SPEC subagent files exist and are up-to-date.

    Creates .augment/agents/ directory and manages agent files:
    - Creates missing agent files with versioned frontmatter
    - Updates outdated files if they haven't been customized by the user
    - Preserves user customizations (creates .md.new file for review)

    Also ensures the project's .gitignore is configured to ignore
    SPECFLOW artifacts (.specflow/ directory, *.log files).

    Args:
        quiet: If True, suppress informational messages

    Returns:
        True if all agents are available (created, updated, or already current)
    """
    # First, ensure .gitignore is configured for SPECFLOW
    # Note: We don't fail the workflow if gitignore update fails, but we log a warning
    if not ensure_gitignore_configured(quiet=quiet):
        if not quiet:
            print_warning("Could not configure .gitignore - workflow artifacts may appear as unversioned")
        log_message("ensure_gitignore_configured returned False")

    agents_dir = get_agents_dir()

    # Track actions taken
    created_agents = []
    updated_agents = []
    customized_agents = []  # Agents with user changes that need manual review

    # Ensure directory exists
    if not agents_dir.exists():
        if not quiet:
            print_step("Creating .augment/agents/ directory...")
        agents_dir.mkdir(parents=True, exist_ok=True)

    # Process each agent
    for agent_name in get_all_agent_names():
        meta = AGENT_METADATA[agent_name]
        agent_filename = f"{meta['name']}.md"
        agent_path = agents_dir / agent_filename

        if not agent_path.exists():
            # Case 1: New installation
            if _create_agent_file(agent_path, agent_name, quiet):
                created_agents.append(meta["name"])
            else:
                return False
        else:
            # Case 2: File exists - check if update needed
            needs_update, is_customized = _check_agent_needs_update(agent_path, agent_name)

            if not needs_update:
                log_message(f"Agent {meta['name']} is up-to-date")
                continue

            if is_customized:
                # User has modified the file - don't overwrite
                # Create a .new file for them to review
                new_path = agent_path.with_suffix(".md.new")
                if _create_agent_file(new_path, agent_name, quiet=True):
                    customized_agents.append(meta["name"])
                    if not quiet:
                        print_warning(
                            f"Agent '{meta['name']}' has local customizations. "
                            f"New version saved to {new_path}"
                        )
                    log_message(
                        f"Agent {meta['name']} has customizations, "
                        f"created {new_path} for review"
                    )
            else:
                # Safe to update - file matches old default
                if _update_agent_file(agent_path, agent_name, quiet):
                    updated_agents.append(meta["name"])
                else:
                    return False

    # Report results
    if not quiet:
        if created_agents:
            print_success(f"Created {len(created_agents)} agent(s): {', '.join(created_agents)}")
        if updated_agents:
            print_success(f"Updated {len(updated_agents)} agent(s): {', '.join(updated_agents)}")
        if customized_agents:
            print_info(
                f"{len(customized_agents)} agent(s) have customizations - "
                "review .md.new files to merge updates"
            )

    if not created_agents and not updated_agents and not customized_agents:
        log_message("All SPEC subagent files are up-to-date")

    return True


def verify_agents_available() -> tuple[bool, list[str]]:
    """Verify that all required SPEC subagent files exist.

    Returns:
        Tuple of (all_available, list_of_missing_agents)
    """
    agents_dir = get_agents_dir()
    missing = []

    for agent_name in ["spec-planner", "spec-tasklist", "spec-implementer"]:
        agent_path = agents_dir / f"{agent_name}.md"
        if not agent_path.exists():
            missing.append(agent_name)

    return len(missing) == 0, missing


__all__ = [
    # Main functions
    "ensure_agents_installed",
    "verify_agents_available",
    "get_agents_dir",
    # Gitignore management
    "ensure_gitignore_configured",
    "SPECFLOW_GITIGNORE_PATTERNS",
    # Agent definitions (compatibility + new APIs)
    "AGENT_DEFINITIONS",
    "AGENT_METADATA",
    "AGENT_BODIES",
    "generate_agent_content",
    "get_agent_body",
    "get_all_agent_names",
    # Frontmatter utilities
    "parse_agent_frontmatter",
    "extract_agent_body",
    "compute_content_hash",
    "normalize_content",
    "is_agent_customized",
]

