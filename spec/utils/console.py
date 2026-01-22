"""Rich-based console output utilities.

This module provides colored terminal output functions that match
the original Bash script's color scheme.
"""

from rich.console import Console
from rich.theme import Theme

from spec import __version__

# Custom theme matching Bash colors
custom_theme = Theme(
    {
        "error": "bold red",
        "success": "bold green",
        "warning": "bold yellow",
        "info": "bold blue",
        "header": "bold magenta",
        "step": "bold cyan",
        "highlight": "bold white",
    }
)

# Global console instances
console = Console(theme=custom_theme)
console_err = Console(theme=custom_theme, stderr=True)


def print_error(message: str) -> None:
    """Print error message in red.

    Args:
        message: Error message to display
    """
    from spec.utils.logging import log_message

    console_err.print(f"[error][[ERROR]][/error] [red]{message}[/red]")
    log_message(f"ERROR: {message}")


def print_success(message: str) -> None:
    """Print success message in green.

    Args:
        message: Success message to display
    """
    from spec.utils.logging import log_message

    console.print(f"[success][[SUCCESS]][/success] [green]{message}[/green]")
    log_message(f"SUCCESS: {message}")


def print_warning(message: str) -> None:
    """Print warning message in yellow.

    Args:
        message: Warning message to display
    """
    from spec.utils.logging import log_message

    console.print(f"[warning][[WARNING]][/warning] [yellow]{message}[/yellow]")
    log_message(f"WARNING: {message}")


def print_info(message: str) -> None:
    """Print info message in blue/cyan.

    Args:
        message: Info message to display
    """
    from spec.utils.logging import log_message

    console.print(f"[info][[INFO]][/info] [cyan]{message}[/cyan]")
    log_message(f"INFO: {message}")


def print_header(title: str) -> None:
    """Print section header in magenta.

    Args:
        title: Header title to display
    """
    console.print()
    console.print(f"[header]=== {title} ===[/header]")
    console.print()


def print_step(message: str) -> None:
    """Print step indicator with arrow.

    Args:
        message: Step message to display
    """
    console.print(f"[step]➜[/step] {message}")


def show_banner() -> None:
    """Display ASCII art banner."""
    banner = """
[bold magenta]   _____ ____  ______ ______
  / ___// __ \\/ ____// ____/
  \\__ \\/ /_/ / __/  / /
 ___/ / ____/ /___ / /___
/____/_/   /_____/ \\____/
[/bold magenta]
[bold cyan]Spec-driven Development Workflow[/bold cyan]
[white]Version {version}[/white]
"""
    console.print(banner.format(version=__version__))


def show_version() -> None:
    """Display version information."""
    from spec import REQUIRED_AUGGIE_VERSION, REQUIRED_NODE_VERSION

    console.print(f"[bold]SPEC[/bold] v{__version__}")
    console.print()
    console.print("Requirements:")
    console.print(f"  - Auggie CLI: >= {REQUIRED_AUGGIE_VERSION}")
    console.print(f"  - Node.js: >= {REQUIRED_NODE_VERSION}")
    console.print()


__all__ = [
    "console",
    "console_err",
    "custom_theme",
    "print_error",
    "print_success",
    "print_warning",
    "print_info",
    "print_header",
    "print_step",
    "show_banner",
    "show_version",
]

