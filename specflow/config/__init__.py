"""Configuration management for SPEC.

This package contains:
- settings: Settings dataclass with configuration fields
- manager: ConfigManager class for loading/saving configuration
"""

from specflow.config.manager import ConfigManager
from specflow.config.settings import Settings

__all__ = [
    "Settings",
    "ConfigManager",
]

