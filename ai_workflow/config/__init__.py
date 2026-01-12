"""Configuration management for AI Workflow.

This package contains:
- settings: Settings dataclass with configuration fields
- manager: ConfigManager class for loading/saving configuration
"""

from ai_workflow.config.manager import ConfigManager
from ai_workflow.config.settings import Settings

__all__ = [
    "Settings",
    "ConfigManager",
]

