# Subagent Integration - Configuration

## Overview

This specification details configuration changes to support subagent integration
in the SPEC workflow.

---

## 1. Settings Updates

**File**: `spec/config/settings.py`

### 1.1 Add Subagent Settings

```python
@dataclass
class Settings:
    # ... existing fields ...

    # Subagent settings (customizable agent names)
    subagent_planner: str = "spec-planner"
    subagent_tasklist: str = "spec-tasklist"
    subagent_implementer: str = "spec-implementer"
    subagent_reviewer: str = "spec-reviewer"
```

### 1.2 Config File Mappings

Add to config file parsing:
```python
SUBAGENT_PLANNER = "spec-planner"
SUBAGENT_TASKLIST = "spec-tasklist"
SUBAGENT_IMPLEMENTER = "spec-implementer"
SUBAGENT_REVIEWER = "spec-reviewer"
```

---

## 2. CLI Argument Updates

**File**: `spec/cli.py` (or main CLI module)

### 2.1 Add Subagent Override Flags (Optional)

```python
@click.option(
    "--planner-agent",
    default=None,
    help="Override planner agent name",
)
@click.option(
    "--implementer-agent",
    default=None,
    help="Override implementer agent name",
)
```

---

## 3. WorkflowState Updates

**File**: `spec/workflow/state.py`

### 3.1 Add Subagent Configuration

```python
@dataclass
class WorkflowState:
    # ... existing fields ...

    # Subagent configuration
    subagent_names: dict[str, str] = field(default_factory=lambda: {
        "planner": "spec-planner",
        "tasklist": "spec-tasklist",
        "implementer": "spec-implementer",
        "reviewer": "spec-reviewer",
    })
```

---

## 4. Environment Variable Support

Support environment variables for CI/automation:

| Variable | Purpose | Default |
|----------|---------|---------|
| `SPEC_AGENT_PLANNER` | Planner agent name | `spec-planner` |
| `SPEC_AGENT_TASKLIST` | Tasklist agent name | `spec-tasklist` |
| `SPEC_AGENT_IMPLEMENTER` | Implementer agent name | `spec-implementer` |

---

## 5. Version Requirements

**File**: `spec.sh` (for bash version) or appropriate Python module

### 5.1 Update Auggie Version Check

```bash
REQUIRED_AUGGIE_VERSION="0.12.0"  # Subagents require 0.12.0+
```

### 5.2 Add Version Check for Subagent Features

```python
def check_subagent_support() -> bool:
    """Check if installed Auggie version supports subagents.
    
    Returns:
        True if subagents are supported (version >= 0.12.0)
    """
    version = get_auggie_version()
    return version_gte(version, "0.12.0")
```

---

## 6. Agent File Installation

### 6.1 First-Run Setup

When SPEC runs for the first time, optionally offer to install default agents:

```python
def ensure_agents_installed() -> None:
    """Ensure SPEC subagent files exist in workspace.
    
    Creates .augment/agents/ directory and copies default agent definitions
    if they don't exist.
    """
    agents_dir = Path(".augment/agents")
    agents_dir.mkdir(parents=True, exist_ok=True)
    
    for agent_name in ["spec-planner", "spec-tasklist", "spec-implementer"]:
        agent_path = agents_dir / f"{agent_name}.md"
        if not agent_path.exists():
            # Copy from package resources or create default
            _create_default_agent(agent_path, agent_name)
```

### 6.2 Package Agent Templates

Include default agent templates in the package:
```
spec/
└── resources/
    └── agents/
        ├── spec-planner.md
        ├── spec-tasklist.md
        └── spec-implementer.md
```

---

## 7. Documentation Updates

### 7.1 README Updates

Add section explaining subagent usage:
- What subagents are
- How to customize them
- How to disable them

### 7.2 Help Text Updates

Update `--help` output to mention subagent options.

---

## Validation Checklist

- [ ] Settings dataclass includes subagent fields
- [ ] Config file parser handles new settings
- [ ] CLI has `--no-subagents` flag
- [ ] Environment variables work correctly
- [ ] Auggie version check updated to 0.12.0
- [ ] Default agent files can be installed
- [ ] Documentation updated

