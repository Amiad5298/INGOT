"""Configuration management for SPEC.

This package contains:
- settings: Settings dataclass with configuration fields
- manager: ConfigManager class for loading/saving configuration
"""

from spec.config.manager import ConfigManager
from spec.config.settings import Settings

__all__ = [
    "Settings",
    "ConfigManager",
]

