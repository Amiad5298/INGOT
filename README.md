# AI Workflow

AI-Assisted Development Workflow using Auggie CLI.

## Overview

AI Workflow is a Python CLI application that provides a structured, spec-driven development workflow using the Auggie AI assistant. It converts the original AI-World.sh Bash script to a modern Python implementation.

## Features

- **Spec-Driven Development**: Three-step workflow (Plan → Task List → Execute)
- **Jira Integration**: Automatic ticket parsing and context fetching
- **Git Integration**: Branch management, checkpoint commits, and squashing
- **Interactive UI**: Rich terminal output with questionary prompts
- **Configurable**: Flexible model selection and workflow options

## Installation

```bash
pip install ai-workflow
```

Or install from source:

```bash
pip install -e ".[dev]"
```

## Usage

### Basic Usage

```bash
# Start workflow with a Jira ticket
ai-workflow PROJECT-123

# Show main menu
ai-workflow

# Show configuration
ai-workflow --config
```

### Options

```bash
ai-workflow [OPTIONS] [TICKET]

Options:
  --model, -m MODEL         Override default AI model
  --planning-model MODEL    Model for planning phases
  --impl-model MODEL        Model for implementation phase
  --skip-clarification      Skip clarification step
  --no-squash               Don't squash commits at end
  --force-jira-check        Force fresh Jira integration check
  --config                  Show current configuration
  --version, -v             Show version information
  --help, -h                Show this help message
```

## Workflow Steps

### Step 1: Create Implementation Plan

- Fetches ticket information from Jira
- Optionally runs clarification with the user
- Generates an implementation plan
- Saves to `specs/{ticket}-plan.md`

### Step 2: Create Task List

- Reads the implementation plan
- Generates a task list with checkboxes
- Allows user to review, edit, or regenerate
- Saves to `specs/{ticket}-tasklist.md`

### Step 3: Execute Implementation

- Executes each task with Auggie
- Creates checkpoint commits after each task
- Optionally squashes commits at the end

## Configuration

Configuration is stored in `~/.ai-workflow/config.env`:

```bash
DEFAULT_MODEL=claude-3-opus
PLANNING_MODEL=claude-3-opus
IMPLEMENTATION_MODEL=claude-3-opus
DEFAULT_JIRA_PROJECT=PROJ
SKIP_CLARIFICATION=false
SQUASH_AT_END=true
```

## Development

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd AI-Platform

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/ -v
```

### Code Quality

```bash
# Format code
black ai_workflow tests
isort ai_workflow tests

# Type checking
mypy ai_workflow

# Linting
ruff check ai_workflow tests
```

## Requirements

- Python 3.11+
- Auggie CLI installed and configured
- Git repository
- Jira integration (optional but recommended)

## License

MIT License

