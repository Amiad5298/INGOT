"""Base classes for INGOT plan and artifact validation.

Provides the Validator ABC, finding/report data classes, and the
ValidatorRegistry that runs all registered validators against content.
"""

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ingot.utils.logging import log_message


class ValidationSeverity(Enum):
    """Severity level for validation findings."""

    INFO = "info"  # Non-actionable observation
    WARNING = "warning"  # Should fix, but won't block
    ERROR = "error"  # Must fix before proceeding


@dataclass
class ValidationFinding:
    """A single validation issue found in the artifact."""

    validator_name: str
    severity: ValidationSeverity
    message: str
    line_number: int | None = None  # Optional: line in the plan where issue was found
    suggestion: str | None = None  # Optional: how to fix
    metadata: dict[str, Any] = field(default_factory=dict)  # Structured data for fixers
    repair_worthy: bool = False  # If True, triggers AI fix even for WARNING findings


@dataclass
class ValidationContext:
    """Context passed to validators for their checks."""

    repo_root: Path | None = None  # For filesystem checks (must be injected, not auto-discovered)
    ticket_id: str = ""  # Reserved for future validator use
    ticket_signals: list[str] = field(
        default_factory=list
    )  # Category signals (e.g., "metric", "alert")
    ticket_files_to_modify: list[str] = field(default_factory=list)
    ticket_acceptance_criteria: list[str] = field(default_factory=list)
    # import_index: maps short_type_name -> set of full import paths.
    # Populated by ImportIndexer; used by EntityDuplicationValidator to detect
    # types available from external dependencies.
    import_index: dict[str, set[str]] = field(default_factory=dict)
    # convention_report: maps collection identifiers to their common wrapping patterns.
    # Populated by SiblingPatternAnalyzer; used by ConventionAdherenceValidator.
    convention_report: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Aggregated results from all validators."""

    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(f.severity == ValidationSeverity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == ValidationSeverity.WARNING for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == ValidationSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == ValidationSeverity.INFO)

    @property
    def has_repair_worthy(self) -> bool:
        """True if any finding is ERROR or a repair-worthy WARNING."""
        return self.has_errors or any(
            f.repair_worthy and f.severity == ValidationSeverity.WARNING for f in self.findings
        )


class Validator(ABC):
    """Base class for all plan/artifact validators.

    To add a new gate: create a class that extends Validator,
    implement name and validate(), then register it in the registry.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable validator name (e.g., 'File Exists Check')."""
        ...

    @abstractmethod
    def validate(self, content: str, context: ValidationContext) -> list[ValidationFinding]:
        """Run validation on content. Return list of findings (empty = pass)."""
        ...


class ValidatorRegistry:
    """Registry of validators. Run all registered validators against content."""

    def __init__(self) -> None:
        self._validators: list[Validator] = []

    def register(self, validator: Validator) -> None:
        self._validators.append(validator)

    def validate_all(self, content: str, context: ValidationContext) -> ValidationReport:
        report = ValidationReport()
        for validator in self._validators:
            try:
                findings = validator.validate(content, context)
                report.findings.extend(findings)
            except Exception as exc:
                log_message(f"Validator '{validator.name}' crashed:\n{traceback.format_exc()}")
                report.findings.append(
                    ValidationFinding(
                        validator_name=validator.name,
                        severity=ValidationSeverity.ERROR,
                        message=f"Validator crashed: {exc}",
                    )
                )
        return report

    @property
    def validators(self) -> list[Validator]:
        return list(self._validators)


__all__ = [
    "ValidationContext",
    "ValidationFinding",
    "ValidationReport",
    "ValidationSeverity",
    "Validator",
    "ValidatorRegistry",
]
