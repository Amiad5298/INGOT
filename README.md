<p align="center">
  <h1 align="center">SPEC</h1>
  <p align="center">
    <strong>Spec-Driven Development Workflow Powered by AI</strong>
  </p>
  <p align="center">
    Transform Jira tickets into implemented features with a structured, AI-assisted three-step workflow.
  </p>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#contributing">Contributing</a>
</p>

---

## What is SPEC?

SPEC is a command-line tool that orchestrates AI agents to implement software features from start to finish. Given a Jira ticket, SPEC:

1. **Plans** - Creates a detailed implementation plan by analyzing requirements and your codebase
2. **Tasks** - Generates an optimized task list, identifying which tasks can run in parallel
3. **Executes** - Runs specialized AI agents to complete each task, with checkpoint commits and progress tracking

SPEC leverages the [Auggie CLI](https://github.com/AugmentCode/auggie) and multiple specialized AI agents to deliver a structured, reproducible development workflow.

[Screenshot placeholder: SPEC main workflow showing the three steps with progress indicators]

## Features

### 🚀 Three-Step Workflow
A structured approach that breaks complex features into manageable pieces:
- **Step 1**: AI-generated implementation plan based on Jira ticket and codebase analysis
- **Step 2**: Task list with dependency analysis for optimal execution order
- **Step 3**: Automated task execution with real-time progress tracking

### ⚡ Parallel Task Execution
Dramatically reduce implementation time:
- Automatically identifies independent tasks that can run concurrently
- Configurable parallelism (1-5 concurrent tasks)
- Fail-fast or continue-on-error modes
- Built-in rate limit handling with exponential backoff

### 🔗 Deep Integrations
- **Jira**: Automatic ticket fetching, context extraction, and branch naming
- **Git**: Feature branch creation, checkpoint commits after each task, optional commit squashing
- **Auggie CLI**: Leverages Auggie's AI capabilities with specialized subagents

### 🎨 Rich Terminal UI
- Real-time task progress visualization
- Log streaming with expandable panels
- Interactive menus for task review and approval
- Works in both TUI mode and simple fallback for CI environments

### 🤖 Specialized AI Agents
Four purpose-built agents work together:
- **spec-planner**: Analyzes requirements and creates implementation plans
- **spec-tasklist**: Converts plans into optimized, executable task lists
- **spec-implementer**: Executes individual tasks with codebase awareness
- **spec-reviewer**: Validates completed work (optional)

[Screenshot placeholder: Terminal showing the TUI with parallel task execution in progress]

## Quick Start

```bash
# Install SPEC
pip install specflow

# Navigate to your git repository
cd your-project

# Start a workflow with a Jira ticket
spec PROJECT-123
```

That's it! SPEC will guide you through the entire workflow with interactive prompts.

[Screenshot placeholder: Quick start workflow showing initial prompts and plan generation]

## How It Works

### The SPEC Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SPEC WORKFLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Jira Ticket                                                            │
│       │                                                                  │
│       ▼                                                                  │
│   ┌───────────────────────────────────────────────────────────┐         │
│   │  STEP 1: PLAN                                              │         │
│   │  • Fetch ticket details from Jira                          │         │
│   │  • Analyze codebase with context retrieval                 │         │
│   │  • Generate implementation plan                            │         │
│   │  • Output: specs/{ticket}-plan.md                          │         │
│   └───────────────────────────────────────────────────────────┘         │
│       │                                                                  │
│       ▼                                                                  │
│   ┌───────────────────────────────────────────────────────────┐         │
│   │  STEP 2: TASK LIST                                         │         │
│   │  • Parse implementation plan                               │         │
│   │  • Generate task list with categories                      │         │
│   │  • User reviews and approves/edits/regenerates             │         │
│   │  • Output: specs/{ticket}-tasklist.md                      │         │
│   └───────────────────────────────────────────────────────────┘         │
│       │                                                                  │
│       ▼                                                                  │
│   ┌───────────────────────────────────────────────────────────┐         │
│   │  STEP 3: EXECUTE                                           │         │
│   │  • Phase 1: Sequential execution of fundamental tasks      │         │
│   │  • Phase 2: Parallel execution of independent tasks        │         │
│   │  • Checkpoint commits after each task                      │         │
│   │  • Optional commit squashing at end                        │         │
│   └───────────────────────────────────────────────────────────┘         │
│       │                                                                  │
│       ▼                                                                  │
│   Implemented Feature (ready for PR)                                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Task Categories

SPEC organizes tasks into two categories for optimal execution:

#### Fundamental Tasks (Sequential)
Tasks that must run in order due to dependencies:
- Database schema changes
- Core model/type definitions
- Shared utilities
- Configuration setup

#### Independent Tasks (Parallel)
Tasks that can run concurrently with no dependencies:
- UI components (after models exist)
- Separate API endpoints
- Test suites
- Documentation updates

### Generated Files

SPEC creates files in the `specs/` directory:

| File | Description |
|------|-------------|
| `specs/{ticket}-plan.md` | Detailed implementation plan with technical approach, steps, and testing strategy |
| `specs/{ticket}-tasklist.md` | Executable task list with categories and checkboxes |

Run logs are stored in `.spec/runs/{ticket}/` for debugging and audit purposes.

## Installation

### Requirements

- **Python 3.11+**
- **Node.js 22+** (for Auggie CLI)
- **Git** (must be run from a git repository)
- **Auggie CLI 0.12.0+** (installed automatically if missing)

### Install from PyPI

```bash
pip install specflow
```

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Amiad5298/Spec.git
cd Spec

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev]"
```

### Verify Installation

```bash
# Check version
spec --version

# View help
spec --help
```

### First Run

On first run, SPEC will:
1. Check for Auggie CLI installation (offer to install if missing)
2. Prompt for Auggie login if needed
3. Check Jira integration status
4. Create agent definition files in `.augment/agents/`

## Usage

### Basic Commands

```bash
# Start workflow with a Jira ticket
spec PROJECT-123

# Start with a full Jira URL
spec https://company.atlassian.net/browse/PROJECT-123

# Show interactive main menu
spec

# View current configuration
spec --config

# Show version
spec --version
```

### Command-Line Options

```bash
spec [OPTIONS] [TICKET]

Arguments:
  TICKET                      Jira ticket ID or URL (e.g., PROJECT-123)

Model Options:
  --model, -m MODEL           Override AI model for all phases
  --planning-model MODEL      Model specifically for Steps 1-2 (planning)
  --impl-model MODEL          Model specifically for Step 3 (implementation)

Workflow Options:
  --skip-clarification        Skip the clarification step
  --no-squash                 Don't squash checkpoint commits at end
  --force-jira-check          Force fresh Jira integration check

Parallel Execution:
  --parallel/--no-parallel    Enable/disable parallel task execution
  --max-parallel N            Maximum parallel tasks (1-5, default: from config)
  --fail-fast/--no-fail-fast  Stop on first task failure

Rate Limiting:
  --max-retries N             Max retries on rate limit (0 to disable)
  --retry-base-delay SECS     Base delay for retry backoff (seconds)

Display Options:
  --tui/--no-tui              Enable/disable TUI mode (default: auto-detect)
  --verbose, -V               Show verbose output in TUI log panel

Other:
  --config                    Show current configuration and exit
  --version, -v               Show version information
  --help, -h                  Show help message
```

### Example Workflows

#### Standard Feature Development

```bash
# Start a new feature
spec PROJ-456

# SPEC will:
# 1. Fetch ticket from Jira
# 2. Ask if you want to add context
# 3. Create feature branch (e.g., proj-456-add-user-authentication)
# 4. Generate implementation plan
# 5. Generate task list (you review/approve)
# 6. Execute tasks with progress tracking
# 7. Squash commits at end
```

#### Fast Mode (Skip Clarification)

```bash
spec PROJ-789 --skip-clarification
```

#### Custom Model Selection

```bash
# Use specific model for planning (faster, cheaper)
spec PROJ-101 --planning-model claude-sonnet-4-5 --impl-model claude-opus-4

# Use same model for everything
spec PROJ-101 --model claude-opus-4
```

#### Parallel Execution Control

```bash
# Run up to 5 tasks in parallel
spec PROJ-202 --max-parallel 5

# Disable parallel execution (sequential only)
spec PROJ-202 --no-parallel

# Stop immediately on any task failure
spec PROJ-202 --fail-fast
```

## Configuration

### Configuration File

SPEC stores configuration in `~/.spec-config`:

```bash
# AI Model Configuration
PLANNING_MODEL="claude-sonnet-4-5"
IMPLEMENTATION_MODEL="claude-sonnet-4-5"

# Jira Settings
DEFAULT_JIRA_PROJECT="PROJ"

# Workflow Behavior
SKIP_CLARIFICATION="false"
SQUASH_AT_END="true"
AUTO_OPEN_FILES="true"

# Parallel Execution
PARALLEL_EXECUTION_ENABLED="true"
MAX_PARALLEL_TASKS="3"
FAIL_FAST="false"

# Custom Subagent Names (advanced)
SUBAGENT_PLANNER="spec-planner"
SUBAGENT_TASKLIST="spec-tasklist"
SUBAGENT_IMPLEMENTER="spec-implementer"
SUBAGENT_REVIEWER="spec-reviewer"
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `PLANNING_MODEL` | string | "" | AI model for Steps 1-2 |
| `IMPLEMENTATION_MODEL` | string | "" | AI model for Step 3 |
| `DEFAULT_JIRA_PROJECT` | string | "" | Default Jira project key |
| `SKIP_CLARIFICATION` | bool | false | Skip clarification step |
| `SQUASH_AT_END` | bool | true | Squash commits after workflow |
| `AUTO_OPEN_FILES` | bool | true | Auto-open generated files |
| `PARALLEL_EXECUTION_ENABLED` | bool | true | Enable parallel task execution |
| `MAX_PARALLEL_TASKS` | int | 3 | Max concurrent tasks (1-5) |
| `FAIL_FAST` | bool | false | Stop on first task failure |

### Interactive Configuration

```bash
# Run SPEC without arguments to access the menu
spec

# Select "Configure settings" from the menu
```

[Screenshot placeholder: Interactive configuration menu]

### View Current Configuration

```bash
spec --config
```

## Agent Customization

SPEC uses specialized AI agents defined in `.augment/agents/`. These are created automatically on first run.

### Agent Files

| File | Purpose |
|------|---------|
| `.augment/agents/spec-planner.md` | Creates implementation plans |
| `.augment/agents/spec-tasklist.md` | Generates task lists |
| `.augment/agents/spec-implementer.md` | Executes individual tasks |
| `.augment/agents/spec-reviewer.md` | Validates completed tasks |

### Customizing Agents

You can modify these files to adjust agent behavior:

```yaml
---
name: spec-planner
description: SPEC workflow planner
model: claude-sonnet-4-5
color: blue
---

# Your custom instructions here...
```

The `model` field in each agent file determines which AI model that agent uses.

## Project Structure

```
spec/
├── __init__.py          # Version and constants
├── cli.py               # CLI entry point and command handling
├── config/
│   ├── manager.py       # Configuration loading/saving
│   └── settings.py      # Settings dataclass
├── integrations/
│   ├── agents.py        # Subagent file management
│   ├── auggie.py        # Auggie CLI wrapper
│   ├── git.py           # Git operations
│   └── jira.py          # Jira ticket parsing
├── ui/
│   ├── menus.py         # Interactive menus
│   ├── prompts.py       # User prompts
│   ├── tui.py           # Terminal UI for execution
│   └── plan_tui.py      # TUI for plan generation
├── utils/
│   ├── console.py       # Rich console output
│   ├── errors.py        # Error handling
│   ├── logging.py       # Logging utilities
│   └── retry.py         # Rate limit retry logic
└── workflow/
    ├── runner.py        # Main workflow orchestration
    ├── state.py         # Workflow state management
    ├── step1_plan.py    # Step 1: Plan creation
    ├── step2_tasklist.py # Step 2: Task list generation
    ├── step3_execute.py # Step 3: Task execution
    ├── tasks.py         # Task parsing and status
    └── task_memory.py   # Cross-task context
```

## Development

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/Amiad5298/Spec.git
cd Spec

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/test_cli.py -v

# Run with verbose output
pytest -v --no-cov
```

### Code Quality

```bash
# Type checking
mypy spec

# Linting
ruff check spec tests

# Fix auto-fixable issues
ruff check --fix spec tests
```

### Test Coverage

The project maintains 80%+ code coverage. Coverage reports are generated in `htmlcov/`:

```bash
pytest --cov=spec --cov-report=html
open htmlcov/index.html
```

## Contributing

We welcome contributions! Here's how to get started:

### Reporting Issues

- Check existing issues before creating a new one
- Include SPEC version, Python version, and OS
- Provide steps to reproduce the issue
- Include relevant error messages and logs

### Submitting Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests: `pytest`
5. Run linting: `ruff check spec tests`
6. Commit with clear messages
7. Push and create a Pull Request

### Development Guidelines

- Follow existing code patterns and style
- Add tests for new functionality
- Update documentation as needed
- Keep commits atomic and well-described

### Code Style

- Use type hints for all function signatures
- Follow PEP 8 (enforced by Ruff)
- Document public APIs with docstrings
- Keep functions focused and testable

## Troubleshooting

### Common Issues

#### "Auggie CLI is not installed"

SPEC requires Auggie CLI. When prompted, allow SPEC to install it, or install manually:

```bash
npm install -g @augmentcode/auggie
auggie login
```

#### "Not in a git repository"

SPEC must be run from within a git repository:

```bash
cd your-project
git init  # if not already a repo
spec PROJECT-123
```

#### Rate Limit Errors

If you encounter rate limits during parallel execution:

```bash
# Reduce parallelism
spec PROJECT-123 --max-parallel 2

# Or increase retry attempts
spec PROJECT-123 --max-retries 10 --retry-base-delay 5
```

#### TUI Display Issues

If the TUI doesn't render correctly:

```bash
# Force simple output mode
spec PROJECT-123 --no-tui
```

### Debug Logging

SPEC writes detailed logs to `.spec/runs/{ticket}/`. Check these for debugging:

```bash
ls -la .spec/runs/PROJECT-123/
cat .spec/runs/PROJECT-123/*/task_*.log
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built on [Auggie CLI](https://github.com/AugmentCode/auggie) by Augment Code
- Uses [Typer](https://typer.tiangolo.com/) for CLI
- Uses [Rich](https://rich.readthedocs.io/) for terminal UI
- Uses [Questionary](https://questionary.readthedocs.io/) for prompts

---

<p align="center">
  Made with ❤️ for developers who want AI to handle the implementation details
</p>

