"""Agent prompt templates loaded from .md files.

Each template file contains the body content (without frontmatter) for an
INGOT subagent. Loading from files keeps ``agents.py`` readable and makes
prompts easier to review in diffs.

Usage::

    from ingot.integrations.agent_templates import load_template

    body = load_template("researcher")
"""

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent


def load_template(name: str) -> str:
    """Load an agent prompt template by name.

    Args:
        name: Template filename without extension (e.g. ``"researcher"``).

    Returns:
        The template content as a string.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    path = _TEMPLATES_DIR / f"{name}.md"
    return path.read_text()


__all__ = ["load_template"]
