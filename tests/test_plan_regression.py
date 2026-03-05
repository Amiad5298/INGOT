"""Regression tests replaying saved plan fixtures through the validator pipeline.

Each fixture represents a known failure category from the root-cause analysis.
Tests ensure validators correctly detect each category of issue.
"""

from pathlib import Path

import pytest

from ingot.validation.base import ValidationContext, ValidationSeverity
from ingot.validation.plan_validators import (
    NamingConsistencyValidator,
    OperationalCompletenessValidator,
    RegistrationIdempotencyValidator,
    RequiredSectionsValidator,
    SnippetCompletenessValidator,
    create_plan_validator_registry,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "plan_regression"


def _load_fixture(name: str) -> str:
    """Load a fixture plan file by name."""
    path = FIXTURES_DIR / name
    assert path.exists(), f"Fixture not found: {path}"
    return path.read_text()


def _context(**kwargs) -> ValidationContext:
    """Create a ValidationContext with optional overrides."""
    return ValidationContext(**kwargs)


# =============================================================================
# Category: Missing Required Sections (F-Structure)
# =============================================================================


class TestMissingSections:
    """Plans missing required sections should be caught by RequiredSectionsValidator."""

    def test_missing_testing_strategy(self):
        plan = _load_fixture("plan_missing_sections.md")
        v = RequiredSectionsValidator()
        findings = v.validate(plan, _context())
        # Plan is missing Testing Strategy, Potential Risks, Out of Scope
        assert len(findings) >= 1
        messages = " ".join(f.message for f in findings)
        assert "Testing Strategy" in messages or "section" in messages.lower()

    def test_full_pipeline_catches_missing_sections(self):
        plan = _load_fixture("plan_missing_sections.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        # Should have errors for missing sections
        assert report.has_errors
        section_findings = [f for f in report.findings if f.validator_name == "Required Sections"]
        assert len(section_findings) >= 1


# =============================================================================
# Category: Framework Anti-Patterns — Dual Registration (F5)
# =============================================================================


class TestDualRegistration:
    """Plans with @Component + @Bean for same class should be flagged."""

    def test_dual_registration_detected(self):
        plan = _load_fixture("plan_dual_registration.md")
        v = RegistrationIdempotencyValidator()
        findings = v.validate(plan, _context())
        assert len(findings) >= 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "Component" in findings[0].message or "Bean" in findings[0].message

    def test_full_pipeline_catches_dual_registration(self):
        plan = _load_fixture("plan_dual_registration.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        reg_findings = [
            f for f in report.findings if f.validator_name == "Registration Idempotency"
        ]
        assert len(reg_findings) >= 1


# =============================================================================
# Category: Incomplete Code Snippets (F9)
# =============================================================================


class TestIncompleteSnippets:
    """Plans with field declarations but no constructors should be flagged."""

    def test_java_fields_without_constructor(self):
        plan = _load_fixture("plan_incomplete_snippets.md")
        v = SnippetCompletenessValidator()
        findings = v.validate(plan, _context())
        # Should find at least 1 incomplete snippet (Java fields without constructor)
        assert len(findings) >= 1
        assert all(f.severity == ValidationSeverity.WARNING for f in findings)

    def test_kotlin_fields_without_init(self):
        plan = _load_fixture("plan_incomplete_snippets.md")
        v = SnippetCompletenessValidator()
        findings = v.validate(plan, _context())
        # Should flag the Kotlin snippet too
        assert len(findings) >= 2  # Both Java and Kotlin snippets

    def test_full_pipeline_catches_incomplete_snippets(self):
        plan = _load_fixture("plan_incomplete_snippets.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        snippet_findings = [
            f for f in report.findings if f.validator_name == "Snippet Completeness"
        ]
        assert len(snippet_findings) >= 1


# =============================================================================
# Category: Naming Inconsistency (F8)
# =============================================================================


class TestNamingInconsistency:
    """Plans with inconsistent separators across formats should be flagged."""

    def test_dot_vs_underscore_detected(self):
        plan = _load_fixture("plan_naming_inconsistency.md")
        v = NamingConsistencyValidator()
        findings = v.validate(plan, _context())
        # alert-threshold vs alert_threshold
        assert len(findings) >= 1
        assert findings[0].severity == ValidationSeverity.WARNING

    def test_full_pipeline_catches_naming(self):
        plan = _load_fixture("plan_naming_inconsistency.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        naming_findings = [f for f in report.findings if f.validator_name == "Naming Consistency"]
        assert len(naming_findings) >= 1


# =============================================================================
# Category: Operational Incompleteness (F10)
# =============================================================================


class TestOperationalCompleteness:
    """Metrics/alert plans without operational elements should be flagged."""

    def test_missing_query_and_escalation(self):
        plan = _load_fixture("plan_ops_incomplete.md")
        v = OperationalCompletenessValidator()
        findings = v.validate(plan, _context())
        assert len(findings) == 1
        msg = findings[0].message
        # Should flag missing query examples and escalation
        assert "query example" in msg
        assert "escalation reference" in msg

    def test_severity_elevated_with_metric_signal(self):
        plan = _load_fixture("plan_ops_incomplete.md")
        v = OperationalCompletenessValidator()
        # With metric signal, severity should be WARNING instead of INFO
        ctx = _context(ticket_signals=["metric", "alert"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING

    def test_severity_info_without_signal(self):
        plan = _load_fixture("plan_ops_incomplete.md")
        v = OperationalCompletenessValidator()
        # Without signals, severity should be INFO
        ctx = _context(ticket_signals=[])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO

    def test_full_pipeline_catches_ops_incomplete(self):
        plan = _load_fixture("plan_ops_incomplete.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        ops_findings = [
            f for f in report.findings if f.validator_name == "Operational Completeness"
        ]
        assert len(ops_findings) >= 1


# =============================================================================
# Cross-Category: Full Pipeline on Realistic Plan
# =============================================================================


class TestCleanPlan:
    """A well-formed plan should produce zero findings."""

    def test_clean_plan_zero_findings(self):
        plan = _load_fixture("plan_clean.md")
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        assert len(report.findings) == 0, (
            f"Expected zero findings for clean plan, got: "
            f"{[(f.validator_name, f.message) for f in report.findings]}"
        )


class TestFullPipelineRegression:
    """Run all fixtures through the full pipeline and verify aggregate results."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "plan_missing_sections.md",
            "plan_dual_registration.md",
            "plan_incomplete_snippets.md",
            "plan_naming_inconsistency.md",
            "plan_ops_incomplete.md",
        ],
    )
    def test_all_fixtures_produce_findings(self, fixture_name):
        """Every regression fixture should produce at least one finding."""
        plan = _load_fixture(fixture_name)
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        assert len(report.findings) > 0, f"No findings for {fixture_name}"

    @pytest.mark.parametrize(
        "fixture_name,expected_validators",
        [
            ("plan_missing_sections.md", ["Required Sections"]),
            ("plan_dual_registration.md", ["Registration Idempotency"]),
            ("plan_incomplete_snippets.md", ["Snippet Completeness"]),
            ("plan_naming_inconsistency.md", ["Naming Consistency"]),
            ("plan_ops_incomplete.md", ["Operational Completeness"]),
        ],
    )
    def test_expected_validators_fire(self, fixture_name, expected_validators):
        """Each fixture should trigger its corresponding validator(s)."""
        plan = _load_fixture(fixture_name)
        registry = create_plan_validator_registry()
        report = registry.validate_all(plan, _context())
        fired = {f.validator_name for f in report.findings}
        for validator_name in expected_validators:
            assert validator_name in fired, (
                f"Expected '{validator_name}' to fire for {fixture_name}, " f"but only got: {fired}"
            )
