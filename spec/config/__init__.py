"""Configuration management for SPEC.

This package contains:
- settings: Settings dataclass with configuration fields
- manager: ConfigManager class for loading/saving configuration
- fetch_config: Fetch strategy configuration classes
"""

from spec.config.fetch_config import (
    AgentConfig,
    AgentPlatform,
    FetchPerformanceConfig,
    FetchStrategy,
    FetchStrategyConfig,
)
from spec.config.manager import ConfigManager
from spec.config.settings import Settings

__all__ = [
    "Settings",
    "ConfigManager",
    "FetchStrategy",
    "AgentPlatform",
    "AgentConfig",
    "FetchStrategyConfig",
    "FetchPerformanceConfig",
]
