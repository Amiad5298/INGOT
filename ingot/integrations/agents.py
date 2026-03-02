"""Subagent file management for INGOT.

This module provides utilities for managing INGOT subagent definition files
in the `.ingot/agents/` directory.

Supports versioned agent files with automatic update detection:
- Adds ingot_version and ingot_content_hash to frontmatter
- Detects when internal templates are newer than on-disk files
- Respects user customizations (won't overwrite modified files)
"""

import hashlib
from collections.abc import Iterator
from pathlib import Path

from ingot import __version__
from ingot.integrations.auggie import version_gte
from ingot.integrations.git import find_repo_root
from ingot.utils.console import print_info, print_step, print_success, print_warning
from ingot.utils.logging import log_message
from ingot.workflow.constants import (
    INGOT_AGENT_IMPLEMENTER,
    INGOT_AGENT_PLANNER,
    INGOT_AGENT_RESEARCHER,
    INGOT_AGENT_REVIEWER,
    INGOT_AGENT_TASKLIST,
    INGOT_AGENT_TASKLIST_REFINER,
)

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
ingot_version: {__version__}
ingot_content_hash: {body_hash}
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
    INGOT_AGENT_RESEARCHER: {
        "name": "ingot-researcher",
        "description": "INGOT codebase researcher - discovers files, patterns, and call sites",
        "model": "claude-sonnet-4-5",
        "color": "yellow",
    },
    INGOT_AGENT_PLANNER: {
        "name": "ingot-planner",
        "description": "INGOT workflow planner - creates implementation plans from requirements",
        "model": "claude-sonnet-4-5",
        "color": "blue",
    },
    INGOT_AGENT_TASKLIST: {
        "name": "ingot-tasklist",
        "description": "INGOT workflow task generator - creates executable task lists",
        "model": "claude-sonnet-4-5",
        "color": "cyan",
    },
    INGOT_AGENT_TASKLIST_REFINER: {
        "name": "ingot-tasklist-refiner",
        "description": "Post-processor that extracts test-related work from FUNDAMENTAL to INDEPENDENT",
        "model": "claude-sonnet-4-5",
        "color": "yellow",
    },
    INGOT_AGENT_IMPLEMENTER: {
        "name": "ingot-implementer",
        "description": "INGOT workflow implementer - executes individual tasks",
        "model": "claude-sonnet-4-5",
        "color": "green",
    },
    INGOT_AGENT_REVIEWER: {
        "name": "ingot-reviewer",
        "description": "INGOT workflow reviewer - validates completed tasks",
        "model": "claude-sonnet-4-5",
        "color": "purple",
    },
}

# Agents required for the core workflow. Optional agents (researcher,
# reviewer, tasklist-refiner) are not checked by verify_agents_available().
_REQUIRED_AGENTS: frozenset[str] = frozenset(
    {
        INGOT_AGENT_PLANNER,
        INGOT_AGENT_TASKLIST,
        INGOT_AGENT_IMPLEMENTER,
    }
)

# Agent body content (prompts) - without frontmatter
# NOTE: Researcher prompt section headings must match RESEARCHER_SECTION_HEADINGS
# in ingot.workflow.constants to stay in sync with truncation logic.
AGENT_BODIES = {
    INGOT_AGENT_RESEARCHER: """
You are a codebase research assistant for the INGOT workflow.
Your ONLY job is to explore the codebase and produce structured discovery output.
You do NOT create implementation plans — another agent will do that using your output.

## Your Task

Given a ticket description and optional user constraints, search the codebase to discover:
1. **Relevant files** — files that will likely need modification or serve as reference
2. **Existing code patterns** — working implementations of similar patterns (with code snippets)
3. **Interface hierarchies** — all implementations, callers, and test mocks for relevant interfaces
4. **Call site maps** — where key methods are called from (with file:line references)
5. **Test coverage** — existing test files that cover the affected components
6. **Module boundaries** — identify which modules/packages own which capabilities
   (e.g., dependency registration, service wiring, configuration loading). For each
   module touched by the ticket, note what runtime services or contexts are available.
7. **Initialization & lifecycle** — discover existing component registration and
   initialization patterns and document them.

## Research Rules

- **Search, don't assume.** Every file path must come from a codebase search result. NEVER guess
  file paths based on naming conventions or training data — use your search tools to verify each
  path exists before including it. For example, do NOT assume a project uses Gradle (`build.gradle`)
  vs Maven (`pom.xml`) — search for the actual build file.
- **Quote what you find.** Include exact code snippets (5-15 lines) for discovered patterns.
- **Be exhaustive on interfaces.** For each interface or abstract class, find ALL implementations
  including test mocks (search for `ABC`, `@abstractmethod`, subclass definitions, `MagicMock`, `@patch`).
- **Cite line numbers.** Every reference must include `file:line` or `file:line-line`.
- **Use full paths.** Always report the complete relative path from the repository root (e.g.,
  `k8s/base/qa-shared-settings/configmaps/aws-marketplace.json`, not just `aws-marketplace.json`).
- **Include full signatures.** When documenting methods in Interface & Class Hierarchy
  or Call Sites, include the complete method signature with parameter types and return
  type. Do NOT abbreviate to just the method name — the planner needs exact types to
  ensure compatibility.
- **Discover environment variants.** Search for environment-specific configuration,
  profile selectors, feature flags, or conditional logic. Document any environment
  branching relevant to the ticket's scope.
- **Respect local discovery.** If the prompt includes a `[SOURCE: LOCAL DISCOVERY]` section,
  those facts are deterministically verified. Do NOT contradict them. Your role shifts from
  raw search to interpretation, prioritization, and gap-filling. Use local discovery as a
  starting point and focus on discovering semantic patterns, architectural intent, and
  relationships the local tools could not detect.
- **State the primary API.** For each pattern you report, state the primary API, class, or
  method being used (e.g., "Uses `Gauge.builder()` from Micrometer" not just "metrics pattern").

## Output Budget Rules

Your output is consumed by another agent with limited context. Follow these caps strictly:
- **Verified Files**: List the top 15 most relevant files, ranked by relevance to the ticket. If more exist, add a count: "(N additional files omitted)".
- **Existing Code Patterns**: Include the top 3 most relevant patterns with full snippets (5-15 lines each). For additional patterns, use pointer-only format: "See `path/to/file:line-line`; omitted for brevity."
- **Snippets**: Keep each snippet to 5-15 lines. If a pattern requires more context, quote the key lines and add: "Full implementation at `file:line-line`."
- **Priority rule**: If your output is growing long, prefer fewer patterns with complete snippets over many patterns with truncated snippets.
- **Module Boundaries**: Include for every module the ticket touches.

## Output Format

Output ONLY the following structured markdown (no commentary outside these sections):

### Verified Files
For each relevant file found (max 15, ranked by relevance):
- `path/to/module.py:line` — Brief description of what it does and why it's relevant

### Existing Code Patterns
For each pattern the implementation should follow (top 3 with snippets):
#### Pattern: [Pattern Name]
Source: `path/to/module.py:start-end`
```python
# Exact code snippet from the codebase (5-15 lines)
```
Why relevant: One sentence explaining why this pattern should be followed.

(Additional patterns as pointer-only: "See `file:line`; omitted for brevity.")

### Interface & Class Hierarchy
For each interface/class that may be modified:
#### `ClassName`
- Implemented by: `ConcreteClass` (`path/to/module.py:line`)
- Implemented by: `AnotherClass` (`path/to/other.py:line`)
- Mocked in: `TestFile` (`tests/test_module.py:line`)

### Call Sites
For each method that may be modified or is relevant:
#### `method_name()`
- Called from: `CallerClass.method()` (`path/to/caller.py:line`)
- Called from: `other_caller.run()` (`path/to/other.py:line`)

### Module Boundaries & Runtime Context
For each module/package relevant to the ticket:
#### `module.path`
- Owns: [capabilities available in this module]
- Runtime context: [services/components available at runtime]
- Initialization pattern: `path/to/file.ext:line` — [how components are registered]
- Cross-module dependencies: [what's imported from other modules, with evidence]

### Test Files
- `tests/test_module.py` — Tests for `ComponentName`, covers [scenarios]
- `tests/test_other.py` — Integration tests for [feature]

### Unresolved
Items you searched for but could not find (important for the planner to know):
- Could not locate: [description of what was searched for and not found]
""",
    INGOT_AGENT_PLANNER: """
You are an implementation planning AI assistant working within the INGOT workflow.
Your role is to analyze requirements and create a comprehensive implementation plan.

## Your Task

Create a detailed implementation plan based on the provided ticket/requirements.
The plan will be used to generate an executable task list for AI agents.

## Analysis Process

1. **Understand Requirements**: Parse the ticket description, acceptance criteria, and any linked context
2. **Consume Codebase Discovery**: The prompt may include:
   - `[SOURCE: LOCAL DISCOVERY]` — deterministically verified facts (file paths, grep matches,
     module structure, test mappings). Treat these as ground truth.
   - `[SOURCE: CODEBASE DISCOVERY]` — AI-discovered context (patterns, call sites, hierarchies).
     Use this as your primary source of truth for semantics and architecture.
   If a pattern source has `<!-- CITATION_MISMATCH -->`, do NOT use that pattern — search for
   the correct one instead. If neither section is present, you MUST independently explore the
   codebase using your available tools to discover file paths, patterns, and call sites.
3. **Verify File Ownership**: Before proposing to modify a file, confirm it appears in the Codebase
   Discovery section or the Unresolved section. If a file is in neither, flag it with
   `<!-- UNVERIFIED: reason -->`. For files that the plan proposes to **create** (they don't exist
   yet), use "Create `path/to/new-file.ext`" or add `<!-- NEW_FILE -->` on the same line.
4. **Verify Cross-Module Dependency Availability**: When proposing to use a dependency from
   module A in module B, verify accessibility using the discovery data.
5. **Check Type Compatibility**: Verify data types match using the discovered code snippets.
6. **Plan Implementation**: Design the solution using the discovered patterns as reference.
   Code snippets MUST cite a `Pattern source:` from the discovery section.
7. **Trace Change Propagation**: Use the discovered Call Sites and Interface Hierarchy to list
   ALL callers, implementations, and test mocks that must be updated.
8. **Plan Testing**: Use the discovered Test Files to identify specific test files and methods
   to extend. Search for additional test files only if the discovery section has gaps.
9. **Map Component Lifecycle**: For every new component, specify when it is created,
   how it is registered/initialized, and whether it needs cleanup at shutdown.
   Reference existing lifecycle patterns from the Codebase Discovery section.
10. **Enumerate Environment Variants**: If the codebase uses multiple environments,
    profiles, or feature flags, check whether the changes need environment-specific
    handling. List any conditional behavior. If none relevant, state so explicitly.

## Output Format

Create a markdown document and save it to the specified path with these sections:

### Summary
Brief summary of what will be implemented and why.

### Technical Approach
Architecture decisions, patterns to follow, and how the solution fits into the existing codebase.

### Implementation Steps
Numbered, ordered steps to implement the feature. Each step MUST reference **exact file paths** (and ideally line ranges) for files to create or modify. Never use vague references like "wherever X is instantiated" or "the relevant config file" — find and name the actual files.

**Important — distinguish new files from existing files:**
- For existing files: "**File**: `path/to/existing.java` (lines X-Y)" — path must exist in the repo.
- For new files: "**File**: Create `path/to/new-file.java`" — use the word "Create" or add `<!-- NEW_FILE -->`.

Each step MUST include one of:
- A **code snippet** showing the implementation pattern (with `Pattern source:` citation), OR
- An **explicit method call chain** showing exactly which methods are called with
  their parameters and return types, OR
- `<!-- TRIVIAL_STEP: description -->` marker for genuinely trivial changes
  (single-line config changes, import additions)

Steps that say "retrieve X" or "call Y" without specifying the exact method,
parameters, and return handling are NOT acceptable.

### Testing Strategy

**Per-component coverage** (one entry for every new/modified file in Implementation Steps):
| Component | Test file | Key scenarios |
|---|---|---|
| `path/to/component.ext` | `path/to/test.ext` | [scenario list] |

- Every file in Implementation Steps must have a test entry or an explicit justification:
  `<!-- NO_TEST_NEEDED: component - reason -->`
- Reference the specific test patterns already in use (assertion style, mocking approach, test config/fixture setup)
- List test infrastructure files that need updates (test configs, fixtures, mock setups)

### Potential Risks or Considerations

Address EACH category (write "None identified" if not applicable):
- **External dependencies**: Other repos, libraries, team coordination needed
- **Prerequisite work**: Changes that must happen first
- **Data integrity / state management**: Staleness, overflow, data loss risks
- **Startup / cold-start behavior**: Fresh start correctness, empty caches, job catch-up
- **Environment / configuration drift**: Dev vs. prod differences, feature flag states
- **Performance / scalability**: Hot paths, latency, memory, N+1 queries
- **Backward compatibility**: Breaking changes to APIs, formats, schemas

### Out of Scope
What this implementation explicitly does NOT include.

## HARD GATES (verify before output)

1. **File paths**: Every **existing** file path must come from the Codebase Discovery section or
   be flagged with `<!-- UNVERIFIED: reason -->`. For **new files** to be created, the line must
   contain "Create" or `<!-- NEW_FILE -->` so validators know the file is intentionally absent.
2. **Code snippets**: Every non-trivial code snippet must cite `Pattern source: path/to/file:lines`
   from the discovery section. If no existing pattern was discovered (common for new configuration
   files, infrastructure definitions, or novel code), use `<!-- NO_EXISTING_PATTERN: desc -->`.
3. **Change propagation**: Every interface/method change must list ALL implementations, callers,
   and test mocks from the discovery section's Interface & Class Hierarchy and Call Sites.
4. **Module placement**: When placing new code in a module, cite evidence from
   Codebase Discovery's "Module Boundaries & Runtime Context" that the module has
   the necessary runtime context. If the module lacks required services, explicitly
   document how the dependency will be made available.
5. **Type consistency**: Every proposed method signature must use types matching
   the existing signatures in the Codebase Discovery section. When introducing a
   new parameter or changing a return type, list ALL callers and implementations
   that must be updated. If type info is missing, flag with
   `<!-- UNVERIFIED: type signature not discovered -->`.
6. **Concrete identifiers**: Every configuration key, metric name, tag value,
   event type, or registration identifier must be spelled out exactly. No
   placeholders like "appropriate tag" or "relevant metric". If the exact value
   depends on an unmade decision, list options and recommend one.
7. **Registration idempotency**: Do NOT propose both annotation-based registration
   (e.g., `@Component`, `@Injectable`) AND explicit registration (e.g., `@Bean` method,
   `provide()`) for the same class. Choose one mechanism per component.
8. **Snippet completeness**: Every code snippet that declares fields/properties
   MUST also show the constructor or initialization logic that sets those fields.
   Incomplete snippets without constructors are NOT acceptable.
9. **Naming consistency**: When the same identifier appears in multiple formats
   (e.g., YAML `snake_case`, Java `camelCase`, Prometheus `dot.separated`),
   document the mapping explicitly. Do NOT use inconsistent separators for the
   same concept across formats.
10. **Operational completeness**: If the plan involves metrics, alerts, or monitoring,
    include: example query/expression for observability tools, threshold values with
    rationale, and escalation or runbook references.

## Guidelines

- Be specific and actionable - vague plans lead to poor task lists
- Every file reference must be an **exact path** verified to exist in the repository. Never propose changes to files you haven't confirmed are in-repo (vs. external dependencies).
- Reference existing code patterns from the Codebase Discovery section
- Consider both happy path and error scenarios
- Keep the plan focused on the ticket scope - don't expand unnecessarily
- Include estimated complexity/effort hints where helpful
- When adding new parameters, classes, or registrations, explicitly trace all call sites and registration points that must be updated as a consequence
- When proposing to use a dependency across module boundaries, verify it is accessible at runtime — do not assume a service or component from one module is available in another without evidence

## Data Provenance Rules

The prompt you receive tags each data section with a SOURCE label. Follow these rules strictly:

- `[SOURCE: VERIFIED PLATFORM DATA]` — This data was fetched from the ticketing platform. You may reference "the ticket" as a source.
- `[SOURCE: USER-PROVIDED CONSTRAINTS & PREFERENCES]` — This was typed by the user. Attribute to "the user" (e.g., "the user mentioned…"), never to "the ticket."
- `[SOURCE: NO VERIFIED PLATFORM DATA]` — The platform returned no content. You MUST NOT say "the ticket requires," "the ticket says," "the ticket describes," or similar. Base the plan only on user-provided constraints and codebase exploration.
- `[SOURCE: LOCAL DISCOVERY]` — Deterministically verified facts from local Python tools (file paths, grep matches, module structure, test mappings). Treat as ground truth. Do NOT contradict these facts.
- `[SOURCE: CODEBASE DISCOVERY]` — AI-discovered context from the researcher agent (patterns, call sites, hierarchies). Use as primary source for semantics and architecture. If a pattern has `<!-- CITATION_MISMATCH -->`, do NOT use it — search for the correct one instead.
- When any field says "Not available," never fabricate requirements from it. State what is unknown and plan around what you can verify.
""",
    INGOT_AGENT_TASKLIST: """
You are a task list generation AI assistant working within the INGOT workflow.
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
""",
    INGOT_AGENT_TASKLIST_REFINER: """
You are a task list post-processor for the INGOT workflow.

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
""",
    INGOT_AGENT_IMPLEMENTER: """
You are a task execution AI assistant working within the INGOT workflow.
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
- Make commits (INGOT handles checkpoint commits)
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

## Dynamic Context

The task prompt may include the following sections:

### Target Files
If the prompt lists "Target files for this task:", focus your modifications on those files.
Do not treat them as exhaustive -- you may need to read other files for context --
but your write operations should target the listed files unless the task requires otherwise.

### User Constraints & Preferences
If the prompt includes "User Constraints & Preferences:", this is information the user provided
at workflow start. Consider it as supplementary guidance for how to approach the task.

## Output

When complete, briefly summarize:
- What was implemented
- Files created/modified
- Tests added
- Any issues encountered or decisions made

Do not output the full file contents unless specifically helpful.
""",
    INGOT_AGENT_REVIEWER: """
You are a task validation AI assistant working within the INGOT workflow.
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

## Dynamic Context

The review prompt may include the following sections:

### User Constraints & Preferences
If the prompt includes "User Constraints & Preferences:", this is information the user provided
at workflow start. Use it to verify that the implementation respects these constraints.

## Guidelines

- Be pragmatic, not pedantic
- Focus on correctness and completeness
- Trust the implementing agent made reasonable decisions
- Only flag genuine problems, not style preferences
- A quick pass is better than no review
""",
}


def get_agent_body(agent_name: str) -> str:
    """Get the body content for an agent (without frontmatter).

    Args:
        agent_name: Agent identifier (e.g., INGOT_AGENT_PLANNER)

    Returns:
        Body content string, stripped of leading/trailing whitespace
    """
    return AGENT_BODIES.get(agent_name, "").strip()


def generate_agent_content(agent_name: str) -> str:
    """Generate full agent file content with versioned frontmatter.

    Combines metadata and body with ingot_version and ingot_content_hash
    in the frontmatter for update detection.

    Args:
        agent_name: Agent identifier (e.g., INGOT_AGENT_PLANNER)

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
    """Get the path to the .ingot/agents directory.

    Returns:
        Path to the agents directory
    """
    return Path(".ingot/agents")


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
    existing_version = existing_meta.get("ingot_version", "0.0.0")

    # Check if current INGOT version is newer
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

# Patterns that INGOT requires in the target project's .gitignore
# Note: We do NOT ignore specs/ because plan and tasklist .md files should be visible to users
# Only runtime artifacts (.ingot/runs/ for logs/state, *.log files) are ignored
# Note: .ingot/agents/ contains project-level config that should be committable
INGOT_GITIGNORE_PATTERNS = [
    ".ingot/runs/",
    "*.log",
]

# Comment marker to identify INGOT-managed section
INGOT_GITIGNORE_MARKER = "# INGOT - Run logs and temporary files"


def _check_gitignore_has_pattern(content: str, pattern: str) -> bool:
    """Check if a .gitignore file contains a specific pattern.

    Handles comments and whitespace. Matches the pattern exactly
    (not as a substring of another pattern).

    Args:
        content: Content of the .gitignore file
        pattern: Pattern to search for (e.g., ".ingot/", "*.log")

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
    """Ensure the target project's .gitignore has INGOT patterns.

    Checks for required patterns (.ingot/, *.log) and appends them
    if missing. Adds patterns in a clearly marked INGOT section.

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
        pattern
        for pattern in INGOT_GITIGNORE_PATTERNS
        if not _check_gitignore_has_pattern(existing_content, pattern)
    ]

    if not missing_patterns:
        log_message(".gitignore already has all required INGOT patterns")
        return True

    # Build the section to append
    lines_to_add = []

    # Add blank line separator if file has content and doesn't end with newlines
    if existing_content and not existing_content.endswith("\n\n"):
        if existing_content.endswith("\n"):
            lines_to_add.append("")
        else:
            lines_to_add.extend(["", ""])

    # Check if we already have the INGOT marker
    has_marker = INGOT_GITIGNORE_MARKER in existing_content

    if not has_marker:
        lines_to_add.append(INGOT_GITIGNORE_MARKER)

    lines_to_add.extend(missing_patterns)
    lines_to_add.append("")  # Trailing newline

    # Append to file
    try:
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines_to_add))

        if not quiet:
            pattern_list = ", ".join(missing_patterns)
            print_info(f"Updated .gitignore with INGOT patterns: {pattern_list}")
        log_message(f"Added patterns to .gitignore: {missing_patterns}")
        return True

    except Exception as e:
        if not quiet:
            print_warning(f"Failed to update .gitignore: {e}")
        log_message(f"Failed to update .gitignore: {e}")
        return False


def ensure_agents_installed(quiet: bool = False) -> bool:
    """Ensure INGOT subagent files exist and are up-to-date.

    Creates .ingot/agents/ directory and manages agent files:
    - Creates missing agent files with versioned frontmatter
    - Updates outdated files if they haven't been customized by the user
    - Preserves user customizations (creates .md.new file for review)

    Also ensures the project's .gitignore is configured to ignore
    INGOT artifacts (.ingot/ directory, *.log files).

    Args:
        quiet: If True, suppress informational messages

    Returns:
        True if all agents are available (created, updated, or already current)
    """
    # First, ensure .gitignore is configured for INGOT
    # Note: We don't fail the workflow if gitignore update fails, but we log a warning
    if not ensure_gitignore_configured(quiet=quiet):
        if not quiet:
            print_warning(
                "Could not configure .gitignore - workflow artifacts may appear as unversioned"
            )
        log_message("ensure_gitignore_configured returned False")

    agents_dir = get_agents_dir()

    # Track actions taken
    created_agents = []
    updated_agents = []
    customized_agents = []  # Agents with user changes that need manual review

    # Ensure directory exists
    if not agents_dir.exists():
        if not quiet:
            print_step("Creating .ingot/agents/ directory...")
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
                        f"Agent {meta['name']} has customizations, created {new_path} for review"
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
        log_message("All INGOT subagent files are up-to-date")

    return True


def verify_agents_available() -> tuple[bool, list[str]]:
    """Verify that all required INGOT subagent files exist.

    Only checks agents listed in ``_REQUIRED_AGENTS``.
    Optional agents (researcher, reviewer, tasklist-refiner) are not
    required for the core workflow and are silently skipped.

    Returns:
        Tuple of (all_available, list_of_missing_required_agents)
    """
    agents_dir = get_agents_dir()
    missing = []

    for agent_key, meta in AGENT_METADATA.items():
        if agent_key not in _REQUIRED_AGENTS:
            continue
        agent_path = agents_dir / f"{meta['name']}.md"
        if not agent_path.exists():
            missing.append(meta["name"])

    return len(missing) == 0, missing


__all__ = [
    # Main functions
    "ensure_agents_installed",
    "verify_agents_available",
    "get_agents_dir",
    # Gitignore management
    "ensure_gitignore_configured",
    "INGOT_GITIGNORE_PATTERNS",
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
