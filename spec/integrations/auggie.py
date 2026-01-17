"""Auggie CLI integration for SPEC.

This module provides the Auggie CLI wrapper, model selection,
version checking, and command execution.
"""

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

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

# Subagent names used by SPEC workflow
SPEC_AGENT_PLANNER = "spec-planner"
SPEC_AGENT_TASKLIST = "spec-tasklist"
SPEC_AGENT_IMPLEMENTER = "spec-implementer"
SPEC_AGENT_REVIEWER = "spec-reviewer"


class AuggieRateLimitError(Exception):
    """Raised when Auggie CLI output indicates a rate limit error."""

    def __init__(self, message: str, output: str):
        super().__init__(message)
        self.output = output


def _looks_like_rate_limit(output: str) -> bool:
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


def get_auggie_version() -> Optional[str]:
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


def get_node_version() -> Optional[str]:
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
        print_error(
            f"Node.js is not installed. Please install Node.js {REQUIRED_NODE_VERSION}+"
        )
        print_info("Visit: https://nodejs.org/")
        return False

    try:
        major_version = int(node_version.split(".")[0])
        if major_version < REQUIRED_NODE_VERSION:
            print_error(
                f"Node.js version {node_version} is too old. "
                f"Required: {REQUIRED_NODE_VERSION}+"
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
        agent: Optional[str] = None,
        model: Optional[str] = None,
        print_mode: bool = False,
        quiet: bool = False,
        dont_save_session: bool = False,
    ) -> list[str]:
        """Build auggie command list.

        This internal helper consolidates command construction logic.

        Args:
            prompt: The prompt to send to Auggie
            agent: Agent to use (model comes from agent definition file)
            model: Override model for this command (ignored when agent is set)
            print_mode: Use --print flag
            quiet: Use --quiet flag
            dont_save_session: Use --dont-save-session flag

        Returns:
            List of command arguments for subprocess
        """
        cmd = ["auggie"]

        # Agent takes precedence - model comes from agent definition file
        if agent:
            cmd.extend(["--agent", agent])
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

        cmd.append(prompt)
        return cmd

    def run(
        self,
        prompt: str,
        *,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        print_mode: bool = False,
        quiet: bool = False,
        dont_save_session: bool = False,
    ) -> subprocess.CompletedProcess:
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

    def run_print(self, prompt: str, **kwargs) -> bool:
        """Run with --print flag, return success status.

        Args:
            prompt: The prompt to send
            **kwargs: Additional arguments for run()

        Returns:
            True if command succeeded
        """
        result = self.run(prompt, print_mode=True, **kwargs)
        return result.returncode == 0

    def run_print_quiet(self, prompt: str, **kwargs) -> str:
        """Run with --print --quiet, return output.

        Args:
            prompt: The prompt to send
            **kwargs: Additional arguments for run()

        Returns:
            Command stdout
        """
        result = self.run(prompt, print_mode=True, quiet=True, **kwargs)
        return result.stdout

    def run_print_with_output(
        self,
        prompt: str,
        *,
        agent: Optional[str] = None,
        model: Optional[str] = None,
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
        agent: Optional[str] = None,
        model: Optional[str] = None,
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
    "_looks_like_rate_limit",
    # Subagent constants
    "SPEC_AGENT_PLANNER",
    "SPEC_AGENT_TASKLIST",
    "SPEC_AGENT_IMPLEMENTER",
    "SPEC_AGENT_REVIEWER",
]

