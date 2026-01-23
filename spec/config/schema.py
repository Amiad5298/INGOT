"""JSON Schema for SPECFLOW fetch configuration.

This module provides JSON Schema validation for the fetch configuration,
enabling validation of YAML/JSON configuration files.
"""

from typing import Any

# JSON Schema for the fetch configuration
FETCH_CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "SPECFLOW Fetch Configuration",
    "description": "Configuration for hybrid ticket fetching architecture",
    "type": "object",
    "properties": {
        "agent": {
            "type": "object",
            "description": "AI agent platform configuration",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["auggie", "claude_desktop", "cursor", "aider", "manual"],
                    "default": "auggie",
                    "description": "The AI agent platform being used",
                },
                "integrations": {
                    "type": "object",
                    "description": "Platform integrations available via agent",
                    "additionalProperties": {"type": "boolean"},
                    "examples": [{"jira": True, "linear": True, "github": False}],
                },
            },
        },
        "fetch_strategy": {
            "type": "object",
            "description": "Ticket fetching strategy configuration",
            "properties": {
                "default": {
                    "type": "string",
                    "enum": ["agent", "direct", "auto"],
                    "default": "auto",
                    "description": "Default fetch strategy for all platforms",
                },
                "per_platform": {
                    "type": "object",
                    "description": "Per-platform strategy overrides",
                    "additionalProperties": {
                        "type": "string",
                        "enum": ["agent", "direct", "auto"],
                    },
                    "examples": [{"azure_devops": "direct", "trello": "direct"}],
                },
            },
        },
        "performance": {
            "type": "object",
            "description": "Performance tuning settings",
            "properties": {
                "cache_duration_hours": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 168,
                    "default": 24,
                    "description": "How long to cache ticket data (hours, max 168/1 week)",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "default": 30,
                    "description": "HTTP request timeout (seconds, max 300/5 min)",
                },
                "max_retries": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 3,
                    "description": "Maximum retry attempts (max 10)",
                },
                "retry_delay_seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 60,
                    "default": 1.0,
                    "description": "Delay between retries (seconds, max 60)",
                },
            },
        },
        "fallback_credentials": {
            "type": "object",
            "description": "Fallback credentials for direct API access",
            "additionalProperties": {
                "type": "object",
                "description": "Credentials for a specific platform",
                "additionalProperties": {"type": "string"},
            },
            "examples": [
                {
                    "jira": {
                        "url": "https://company.atlassian.net",
                        "email": "user@example.com",
                        "token": "${JIRA_TOKEN}",
                    },
                    "azure_devops": {"organization": "myorg", "pat": "${AZURE_PAT}"},
                }
            ],
        },
    },
    "additionalProperties": False,
}


def get_schema() -> dict[str, Any]:
    """Get the JSON Schema for fetch configuration.

    Returns:
        The JSON Schema dictionary
    """
    return FETCH_CONFIG_SCHEMA


def validate_config_dict(config: dict[str, Any]) -> list[str]:
    """Validate a configuration dictionary against the schema.

    Uses jsonschema if available, otherwise performs basic validation.

    Args:
        config: Configuration dictionary to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    try:
        import jsonschema  # type: ignore[import-untyped]

        validator = jsonschema.Draft7Validator(FETCH_CONFIG_SCHEMA)
        for error in validator.iter_errors(config):
            path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
            errors.append(f"{path}: {error.message}")
    except ImportError:
        # Fallback: basic validation without jsonschema
        errors = _basic_validate(config)

    return errors


def _basic_validate(config: dict[str, Any]) -> list[str]:
    """Perform basic validation without jsonschema dependency."""
    errors: list[str] = []
    valid_strategies = {"agent", "direct", "auto"}
    valid_platforms = {"auggie", "claude_desktop", "cursor", "aider", "manual"}

    if "agent" in config:
        agent = config["agent"]
        if "platform" in agent and agent["platform"] not in valid_platforms:
            errors.append(f"agent.platform: must be one of {valid_platforms}")

    if "fetch_strategy" in config:
        fs = config["fetch_strategy"]
        if "default" in fs and fs["default"] not in valid_strategies:
            errors.append(f"fetch_strategy.default: must be one of {valid_strategies}")

    return errors


__all__ = ["FETCH_CONFIG_SCHEMA", "get_schema", "validate_config_dict"]
