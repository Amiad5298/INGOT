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
from ingot.integrations.agent_templates import load_template
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
# All prompts are loaded from .md template files in agent_templates/ to keep
# this module readable and make prompts easier to review in diffs.
AGENT_BODIES = {
    INGOT_AGENT_RESEARCHER: load_template("researcher"),
    INGOT_AGENT_PLANNER: load_template("planner"),
    INGOT_AGENT_TASKLIST: load_template("tasklist"),
    INGOT_AGENT_TASKLIST_REFINER: load_template("tasklist_refiner"),
    INGOT_AGENT_IMPLEMENTER: load_template("implementer"),
    INGOT_AGENT_REVIEWER: load_template("reviewer"),
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


def apply_model_overrides(overrides: dict[str, str]) -> None:
    """Patch the model field in agent frontmatter to match user config.

    Called after ensure_agents_installed() so that agent files on disk
    reflect the user's configured planning_model / implementation_model
    rather than the hardcoded default from AGENT_METADATA.

    Args:
        overrides: Mapping of agent name (e.g. "ingot-planner") to model ID.
    """
    if not overrides:
        return
    agents_dir = get_agents_dir()
    for agent_name, model in overrides.items():
        agent_path = agents_dir / f"{agent_name}.md"
        if not agent_path.exists():
            continue
        content = agent_path.read_text()
        # Verify the file has frontmatter and check current model
        frontmatter = parse_agent_frontmatter(content)
        if not frontmatter or frontmatter.get("model") == model:
            continue  # No frontmatter or already correct
        # Replace the model line within frontmatter
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("model:"):
                lines[i] = f"model: {model}"
                break
            if line.strip() == "---" and i > 0:
                break  # Past frontmatter without finding model line
        agent_path.write_text("\n".join(lines))


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
    "apply_model_overrides",
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
