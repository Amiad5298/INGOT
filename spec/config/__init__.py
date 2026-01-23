"""Configuration management for SPEC.

This package contains:
- settings: Settings dataclass with configuration fields
- manager: ConfigManager class for loading/saving configuration
- fetch_config: Fetch strategy configuration classes and validation
- schema: JSON Schema for configuration validation
"""

from spec.config.fetch_config import (
    KNOWN_PLATFORMS,
    MAX_CACHE_DURATION_HOURS,
    MAX_RETRIES,
    MAX_RETRY_DELAY_SECONDS,
    MAX_TIMEOUT_SECONDS,
    PLATFORM_REQUIRED_CREDENTIALS,
    AgentConfig,
    AgentPlatform,
    ConfigValidationError,
    FetchPerformanceConfig,
    FetchStrategy,
    FetchStrategyConfig,
    validate_credentials,
    validate_strategy_for_platform,
)
from spec.config.manager import SENSITIVE_KEY_PATTERNS, ConfigManager, EnvVarExpansionError
from spec.config.schema import FETCH_CONFIG_SCHEMA, get_schema, validate_config_dict
from spec.config.settings import Settings

__all__ = [
    # Core classes
    "Settings",
    "ConfigManager",
    # Fetch strategy enums and dataclasses
    "FetchStrategy",
    "AgentPlatform",
    "AgentConfig",
    "FetchStrategyConfig",
    "FetchPerformanceConfig",
    # Validation
    "ConfigValidationError",
    "EnvVarExpansionError",
    "validate_credentials",
    "validate_strategy_for_platform",
    # Schema
    "FETCH_CONFIG_SCHEMA",
    "get_schema",
    "validate_config_dict",
    # Constants
    "KNOWN_PLATFORMS",
    "PLATFORM_REQUIRED_CREDENTIALS",
    "SENSITIVE_KEY_PATTERNS",
    "MAX_CACHE_DURATION_HOURS",
    "MAX_TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "MAX_RETRY_DELAY_SECONDS",
]
