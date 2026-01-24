"""Environment variable utilities for SPEC.

This module provides utilities for environment variable expansion,
with support for sensitive key detection to prevent logging secrets.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

# Keys containing these substrings are considered sensitive and should not be logged
SENSITIVE_KEY_PATTERNS = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PAT", "CREDENTIAL")

logger = logging.getLogger(__name__)


class EnvVarExpansionError(Exception):
    """Raised when environment variable expansion fails in strict mode."""

    pass


def is_sensitive_key(key: str) -> bool:
    """Check if a configuration key contains sensitive data.

    Args:
        key: The configuration key name

    Returns:
        True if the key is considered sensitive
    """
    key_upper = key.upper()
    return any(pattern in key_upper for pattern in SENSITIVE_KEY_PATTERNS)


def expand_env_vars(
    value: Any,
    strict: bool = False,
    context: str = "",
) -> Any:
    """Recursively expand ${VAR} references to environment variables.

    Supports nested structures (dicts, lists) and can operate in strict mode
    where missing environment variables cause an error.

    Args:
        value: The value to expand (string, dict, list, or other)
        strict: If True, raises EnvVarExpansionError for missing env vars.
                If False, preserves the ${VAR} pattern for debugging.
        context: Context string for error messages (e.g., key name).
                 If context contains sensitive key patterns, it will not
                 be included in log messages.

    Returns:
        The value with ${VAR} references replaced with environment values

    Raises:
        EnvVarExpansionError: If strict=True and an env var is not set
    """
    if isinstance(value, str):
        pattern = r"\$\{([^}]+)\}"
        missing_vars: list[str] = []

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                missing_vars.append(var_name)
                if strict:
                    return match.group(0)  # Will error after
                else:
                    # Warn about missing var, but avoid logging sensitive context
                    if context and not is_sensitive_key(context):
                        logger.warning(f"Environment variable '{var_name}' not set in {context}")
                    else:
                        logger.warning(f"Environment variable '{var_name}' not set")
                    return match.group(0)
            return env_value

        result = re.sub(pattern, replace, value)

        if strict and missing_vars:
            # Build error message, but avoid exposing sensitive context details
            if context and not is_sensitive_key(context):
                raise EnvVarExpansionError(
                    f"Missing environment variable(s): {', '.join(missing_vars)} in {context}"
                )
            else:
                raise EnvVarExpansionError(
                    f"Missing environment variable(s): {', '.join(missing_vars)}"
                )

        return result
    elif isinstance(value, dict):
        return {
            k: expand_env_vars(
                v,
                strict=strict,
                context=f"{context}.{k}" if context else k,
            )
            for k, v in value.items()
        }
    elif isinstance(value, list):
        return [
            expand_env_vars(
                v,
                strict=strict,
                context=f"{context}[{i}]" if context else f"[{i}]",
            )
            for i, v in enumerate(value)
        ]
    return value


def expand_env_vars_strict(value: Any, context: str = "") -> Any:
    """Expand environment variables in strict mode (errors on missing vars).

    Use this for credential expansion where missing vars indicate misconfiguration.

    Args:
        value: The value to expand
        context: Context string for error messages

    Returns:
        The expanded value

    Raises:
        EnvVarExpansionError: If any referenced env var is not set
    """
    return expand_env_vars(value, strict=True, context=context)


__all__ = [
    "EnvVarExpansionError",
    "SENSITIVE_KEY_PATTERNS",
    "expand_env_vars",
    "expand_env_vars_strict",
    "is_sensitive_key",
]
