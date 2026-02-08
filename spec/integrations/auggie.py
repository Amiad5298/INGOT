"""Auggie CLI integration for SPEC.

This module provides the Auggie CLI wrapper, model selection,
version checking, and command execution.
"""

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from packaging import version

from spec import REQUIRED_AUGGIE_VERSION, REQUIRED_NODE_VERSION
from spec.utils.console import (
    print_error,
    print_header,
    print_info,
    print_step,
    print_success,
    print_warning,
)
from spec.utils.logging import log_command, log_message


@dataclass
class AgentDefinition:
    """Parsed agent definition from a markdown file."""

    name: str
    model: str
    prompt: str
    description: str = ""
    color: str = ""


def _find_agent_file(agent_name: str) -> Path | None:
    """Find the agent definition file for a given agent name.

    Searches in workspace (.augment/agents/) and user (~/.augment/agents/) locations.

    Args:
        agent_name: Name of the agent to find

    Returns:
        Path to the agent file if found, None otherwise
    """
    # Check workspace first
    workspace_path = Path(".augment/agents") / f"{agent_name}.md"
    if workspace_path.exists():
        return workspace_path

    # Check user directory
    user_path = Path.home() / ".augment/agents" / f"{agent_name}.md"
    if user_path.exists():
        return user_path

    return None


def _parse_simple_yaml_frontmatter(frontmatter_str: str) -> dict[str, str]:
    """Parse simple YAML frontmatter (key: value pairs only).

    This is a lightweight parser that handles the simple key: value format
    used in agent definition files without requiring the yaml library.

    Args:
        frontmatter_str: The YAML frontmatter string (without --- markers)

    Returns:
        Dictionary of key-value pairs
    """
    result: dict[str, str] = {}
    for line in frontmatter_str.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _parse_agent_definition(agent_name: str) -> AgentDefinition | None:
    """Parse an agent definition file.

    Reads the markdown file with YAML frontmatter and extracts
    the model, prompt, and other configuration.

    Args:
        agent_name: Name of the agent to parse

    Returns:
        AgentDefinition if found and parsed, None otherwise
    """
    agent_file = _find_agent_file(agent_name)
    if not agent_file:
        return None

    try:
        content = agent_file.read_text()

        # Parse YAML frontmatter (between --- markers)
        if not content.startswith("---"):
            return None

        # Find the end of frontmatter
        end_marker = content.find("---", 3)
        if end_marker == -1:
            return None

        frontmatter_str = content[3:end_marker].strip()
        prompt = content[end_marker + 3 :].strip()

        frontmatter = _parse_simple_yaml_frontmatter(frontmatter_str)
        if not frontmatter:
            return None

        return AgentDefinition(
            name=frontmatter.get("name", agent_name),
            model=frontmatter.get("model", ""),
            description=frontmatter.get("description", ""),
            color=frontmatter.get("color", ""),
            prompt=prompt,
        )
    except OSError:
        return None


class AuggieRateLimitError(Exception):
    """Raised when Auggie CLI output indicates a rate limit error."""

    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


def looks_like_rate_limit(output: str) -> bool:
    """Heuristic check for rate limit errors in output.

    Detects rate limit errors by checking for common HTTP status codes
    and rate limit keywords in the output.

    Args:
        output: The output string to check

    Returns:
        True if the output looks like a rate limit error
    """
    output_lower = output.lower()
    patterns = [
        "429",
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota exceeded",
        "capacity",
        "throttl",
        "502",
        "503",
        "504",
    ]
    return any(p in output_lower for p in patterns)


@dataclass
class AuggieModel:
    """Auggie model information.

    Attributes:
        name: Display name of the model
        id: Model identifier for CLI
        description: Optional description
    """

    name: str
    id: str
    description: str = ""


def extract_model_id(model_string: str) -> str:
    """Extract model ID from format 'Name [id]' or return as-is.

    This handles both formats:
    - Full format: "Claude Opus 4.5 [opus4.5]" -> "opus4.5"
    - ID only: "opus4.5" -> "opus4.5"

    Args:
        model_string: Model string in either format

    Returns:
        Model ID suitable for --model flag
    """
    if not model_string:
        return ""

    # Try to extract ID from "Name [id]" format
    match = re.match(r"^.+\[([^\]]+)\]$", model_string.strip())
    if match:
        return match.group(1)

    # Already in ID format, return as-is
    return model_string.strip()


def version_gte(v1: str, v2: str) -> bool:
    """Check if version v1 >= v2.

    Uses packaging.version for robust semver comparison.
    Handles versions like "1.2.3", "1.2", "1", "1.2.3-beta".

    Args:
        v1: First version string
        v2: Second version string

    Returns:
        True if v1 >= v2
    """
    try:
        return version.parse(v1) >= version.parse(v2)
    except version.InvalidVersion:
        # Fallback to simple string comparison
        return v1 >= v2


def get_auggie_version() -> str | None:
    """Get installed Auggie CLI version.

    Returns:
        Version string (e.g., "0.12.0") or None if not installed
    """
    if not shutil.which("auggie"):
        return None

    try:
        result = subprocess.run(
            ["auggie", "--version"],
            capture_output=True,
            text=True,
        )
        log_command("auggie --version", result.returncode)

        # Extract version number (e.g., "0.12.0")
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else None
    except Exception as e:
        log_message(f"Failed to get Auggie version: {e}")
        return None


def get_node_version() -> str | None:
    """Get installed Node.js version.

    Returns:
        Version string (e.g., "22.0.0") or None if not installed
    """
    if not shutil.which("node"):
        return None

    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
        )
        # Remove 'v' prefix (e.g., "v22.0.0" -> "22.0.0")
        version_str = result.stdout.strip().lstrip("v")
        return version_str
    except Exception:
        return None


def check_auggie_installed() -> tuple[bool, str]:
    """Check if Auggie CLI is installed and meets version requirements.

    Returns:
        (is_valid, message) tuple
    """
    print_step("Checking for Auggie CLI installation...")

    auggie_version = get_auggie_version()

    if not auggie_version:
        return False, "Auggie CLI is not installed"

    print_info(f"Found Auggie CLI version: {auggie_version}")

    if not version_gte(auggie_version, REQUIRED_AUGGIE_VERSION):
        return False, (
            f"Auggie CLI version {auggie_version} is older than "
            f"required version {REQUIRED_AUGGIE_VERSION}"
        )

    print_success("Auggie CLI is installed and meets version requirements")
    return True, ""


def install_auggie() -> bool:
    """Install Auggie CLI via npm.

    Returns:
        True if installation successful
    """
    print_header("Installing Auggie CLI")

    # Check Node.js version
    print_step("Checking Node.js version...")
    node_version = get_node_version()

    if not node_version:
        print_error(f"Node.js is not installed. Please install Node.js {REQUIRED_NODE_VERSION}+")
        print_info("Visit: https://nodejs.org/")
        return False

    try:
        major_version = int(node_version.split(".")[0])
        if major_version < REQUIRED_NODE_VERSION:
            print_error(
                f"Node.js version {node_version} is too old. " f"Required: {REQUIRED_NODE_VERSION}+"
            )
            print_info("Please upgrade Node.js: https://nodejs.org/")
            return False
    except ValueError:
        print_warning(f"Could not parse Node.js version: {node_version}")

    print_success(f"Node.js version {node_version} meets requirements")

    # Install via npm
    print_step("Installing Auggie CLI via npm...")
    try:
        result = subprocess.run(
            ["npm", "install", "-g", "@augmentcode/auggie"],
            check=True,
            capture_output=True,
            text=True,
        )
        log_command("npm install -g @augmentcode/auggie", result.returncode)
    except subprocess.CalledProcessError as e:
        log_command("npm install -g @augmentcode/auggie", e.returncode)
        print_error("Failed to install Auggie CLI")
        return False

    print_success("Auggie CLI installed successfully")

    # Guide through login
    print_header("Auggie CLI Login")
    print_info("You need to log in to Auggie CLI to use this script.")
    print_info("This will open a browser window for authentication.")

    from spec.ui.prompts import prompt_confirm

    if prompt_confirm("Would you like to log in now?"):
        print_step("Running 'auggie login'...")
        try:
            subprocess.run(["auggie", "login"], check=True)
            print_success("Successfully logged in to Auggie CLI")
        except subprocess.CalledProcessError:
            print_error("Failed to log in to Auggie CLI")
            return False
    else:
        print_warning("Skipping login. You can run 'auggie login' manually later.")

    return True


class AuggieClient:
    """Wrapper for Auggie CLI commands.

    Attributes:
        model: Default model to use for commands
    """

    def __init__(self, model: str = "") -> None:
        """Initialize the Auggie client.

        Args:
            model: Default model to use for commands (accepts both "Name [id]" and "id" formats)
        """
        # Extract model ID if in "Name [id]" format
        self.model = extract_model_id(model)

    def _build_command(
        self,
        prompt: str,
        agent: str | None = None,
        model: str | None = None,
        print_mode: bool = False,
        quiet: bool = False,
        dont_save_session: bool = False,
    ) -> list[str]:
        """Build auggie command list.

        This internal helper consolidates command construction logic.

        When an agent is specified, the agent definition file is parsed to extract
        the model and system prompt. The agent's prompt is prepended to the user's
        prompt, and the model from the agent definition is used.

        Note: The auggie CLI does not have an --agent flag. Subagents are invoked
        by embedding their instructions in the prompt and using their model.

        Args:
            prompt: The prompt to send to Auggie
            agent: Agent name to use (reads model and prompt from agent definition file)
            model: Override model for this command (ignored when agent is set)
            print_mode: Use --print flag
            quiet: Use --quiet flag
            dont_save_session: Use --dont-save-session flag

        Returns:
            List of command arguments for subprocess
        """
        cmd = ["auggie"]
        effective_prompt = prompt

        # Agent takes precedence - parse agent definition for model and prompt
        if agent:
            agent_def = _parse_agent_definition(agent)
            if agent_def:
                # Use model from agent definition
                if agent_def.model:
                    cmd.extend(["--model", agent_def.model])
                # Prepend agent's system prompt to user's prompt
                if agent_def.prompt:
                    effective_prompt = (
                        f"## Agent Instructions\n\n{agent_def.prompt}\n\n" f"## Task\n\n{prompt}"
                    )
            else:
                # Agent not found, fall back to default model
                effective_model = model or self.model
                if effective_model:
                    cmd.extend(["--model", effective_model])
        else:
            effective_model = model or self.model
            if effective_model:
                cmd.extend(["--model", effective_model])

        if dont_save_session:
            cmd.append("--dont-save-session")

        if print_mode:
            cmd.append("--print")

        if quiet:
            cmd.append("--quiet")

        cmd.append(effective_prompt)
        return cmd

    def run(
        self,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        print_mode: bool = False,
        quiet: bool = False,
        dont_save_session: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run an Auggie command.

        Args:
            prompt: The prompt to send to Auggie
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            print_mode: Use --print flag
            quiet: Use --quiet flag
            dont_save_session: Use --dont-save-session flag

        Returns:
            CompletedProcess with command results
        """
        cmd = self._build_command(
            prompt,
            agent=agent,
            model=model,
            print_mode=print_mode,
            quiet=quiet,
            dont_save_session=dont_save_session,
        )

        log_message(f"Running auggie command: {' '.join(cmd[:3])}...")
        # When using --print --quiet together, we still need to capture output
        # because the caller expects to parse the response (e.g., run_print_quiet)
        # The --quiet flag suppresses Auggie's internal output, but we still
        # need to capture the AI's response for parsing
        should_capture = not print_mode or quiet
        result = subprocess.run(cmd, capture_output=should_capture, text=True)
        log_command(" ".join(cmd), result.returncode)

        return result

    def run_print(
        self,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> bool:
        """Run with --print flag, return success status.

        Args:
            prompt: The prompt to send
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            dont_save_session: Use --dont-save-session flag

        Returns:
            True if command succeeded
        """
        result = self.run(
            prompt,
            print_mode=True,
            agent=agent,
            model=model,
            dont_save_session=dont_save_session,
        )
        return result.returncode == 0

    def run_print_quiet(
        self,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> str:
        """Run with --print --quiet, return output.

        Args:
            prompt: The prompt to send
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            dont_save_session: Use --dont-save-session flag

        Returns:
            Command stdout
        """
        result = self.run(
            prompt,
            print_mode=True,
            quiet=True,
            agent=agent,
            model=model,
            dont_save_session=dont_save_session,
        )
        return str(result.stdout) if result.stdout else ""

    def run_print_with_output(
        self,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Run with --print flag, return success status and captured output.

        This method both prints output to terminal in real-time AND captures
        the full output for parsing. Uses run_with_callback internally.

        Args:
            prompt: The prompt to send
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            dont_save_session: Use --dont-save-session flag

        Returns:
            Tuple of (success: bool, output: str) where output contains the
            full AI response
        """
        # Use run_with_callback with a print callback to both display
        # and capture output. This ensures we can parse the AI response
        # while still showing it to the user in real-time.
        return self.run_with_callback(
            prompt,
            output_callback=lambda line: print(line),
            agent=agent,
            model=model,
            dont_save_session=dont_save_session,
        )

    def run_with_callback(
        self,
        prompt: str,
        *,
        output_callback: Callable[[str], None],
        agent: str | None = None,
        model: str | None = None,
        dont_save_session: bool = False,
    ) -> tuple[bool, str]:
        """Run with streaming output callback.

        Uses subprocess.Popen with line-by-line output processing.
        Each line is passed to output_callback AND collected for return.
        This enables real-time streaming of output while still capturing
        the full response.

        Args:
            prompt: The prompt to send to Auggie
            output_callback: Callback function invoked for each output line
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            dont_save_session: Use --dont-save-session flag

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        cmd = self._build_command(
            prompt,
            agent=agent,
            model=model,
            print_mode=True,
            dont_save_session=dont_save_session,
        )
        return self._run_command_with_callback(cmd, output_callback)

    def run_argv_with_callback(
        self,
        argv: list[str],
        *,
        output_callback: Callable[[str], None],
    ) -> tuple[bool, str]:
        """Run auggie with raw argv arguments (for testing CLI error paths).

        Unlike run_with_callback which builds a prompt-based command,
        this method passes argv directly to the auggie subprocess.
        This is useful for testing CLI failure modes (e.g., invalid flags).

        Args:
            argv: Raw argument list to pass after 'auggie' (e.g., ['--invalid-flag'])
            output_callback: Callback function invoked for each output line

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        cmd = ["auggie"] + argv
        return self._run_command_with_callback(cmd, output_callback)

    def _run_command_with_callback(
        self,
        cmd: list[str],
        output_callback: Callable[[str], None],
    ) -> tuple[bool, str]:
        """Execute a command with streaming output callback.

        Internal helper used by run_with_callback and run_argv_with_callback.

        Args:
            cmd: Full command list to execute
            output_callback: Callback function invoked for each output line

        Returns:
            Tuple of (success: bool, full_output: str)
        """
        log_message(f"Running auggie command with callback: {' '.join(cmd[:3])}...")

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,  # Prevent subprocess from consuming parent stdin
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )

        output_lines = []
        if process.stdout is not None:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                output_callback(stripped)
                output_lines.append(line)

        process.wait()
        log_command(" ".join(cmd), process.returncode)

        return process.returncode == 0, "".join(output_lines)


def list_models() -> list[AuggieModel]:
    """Get list of available models from Auggie.

    Returns:
        List of AuggieModel objects
    """
    try:
        result = subprocess.run(
            ["auggie", "models", "list"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try fallback command
            result = subprocess.run(
                ["auggie", "model", "list"],
                capture_output=True,
                text=True,
            )

        return _parse_model_list(result.stdout)
    except Exception as e:
        log_message(f"Failed to list models: {e}")
        return []


def _parse_model_list(output: str) -> list[AuggieModel]:
    """Parse model list output.

    Args:
        output: Raw output from auggie models list

    Returns:
        List of AuggieModel objects
    """
    models = []
    # Pattern: " - Model Name [model-id]"
    pattern = r"^\s*[-*]\s+(.+)\s+\[([^\]]+)\]\s*$"

    for line in output.splitlines():
        match = re.match(pattern, line)
        if match:
            models.append(
                AuggieModel(
                    name=match.group(1).strip(),
                    id=match.group(2),
                )
            )

    return models


__all__ = [
    "AuggieModel",
    "AuggieClient",
    "AuggieRateLimitError",
    "extract_model_id",
    "version_gte",
    "get_auggie_version",
    "get_node_version",
    "check_auggie_installed",
    "install_auggie",
    "list_models",
    "looks_like_rate_limit",
]
