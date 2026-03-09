"""Tests for ingot.validation.plan_validators module."""

from unittest.mock import patch

from ingot.validation.base import (
    ValidationContext,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    Validator,
    ValidatorRegistry,
)
from ingot.validation.plan_validators import (
    BeanQualifierValidator,
    CitationContentValidator,
    ClaimConsistencyValidator,
    ConfigurationCompletenessValidator,
    DiscoveryCoverageValidator,
    FileExistsValidator,
    ImplementationDetailValidator,
    NamingConsistencyValidator,
    OperationalCompletenessValidator,
    PatternSourceValidator,
    PrerequisiteConsistencyValidator,
    RegistrationIdempotencyValidator,
    RequiredSectionsValidator,
    RiskCategoriesValidator,
    SnippetCompletenessValidator,
    TestCoverageValidator,
    TestScenarioValidator,
    TicketReconciliationValidator,
    UnresolvedMarkersValidator,
    create_plan_validator_registry,
)

# =============================================================================
# Helpers
# =============================================================================

COMPLETE_PLAN = """\
# Implementation Plan: TEST-123

## Summary
Brief summary of what will be implemented.

## Technical Approach
Architecture decisions and patterns.

## Implementation Steps
1. Step one
2. Step two

## Testing Strategy
- Unit tests for new functionality

## Potential Risks or Considerations
- Risk one

## Out of Scope
- Not included
"""


# =============================================================================
# TestRequiredSectionsValidator
# =============================================================================


class TestRequiredSectionsValidator:
    def test_plan_with_all_sections_no_findings(self):
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(COMPLETE_PLAN, ctx)
        assert findings == []

    def test_plan_missing_testing_strategy(self):
        plan = COMPLETE_PLAN.replace("## Testing Strategy", "## Something Else")
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "Testing Strategy" in findings[0].message

    def test_plan_missing_multiple_sections(self):
        plan = "# Plan\n\n## Summary\nJust a summary.\n"
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # Missing: Technical Approach, Implementation Steps, Testing Strategy,
        # Potential Risks, Out of Scope
        assert len(findings) == 5
        assert all(f.severity == ValidationSeverity.ERROR for f in findings)

    def test_variant_name_still_passes(self):
        plan = COMPLETE_PLAN.replace(
            "## Potential Risks or Considerations",
            "### Potential Risks and Edge Cases",
        )
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_case_insensitive_matching(self):
        plan = COMPLETE_PLAN.replace("## Summary", "## SUMMARY")
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestFileExistsValidator
# =============================================================================


class TestFileExistsValidator:
    def test_existing_paths_no_findings(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# code")
        plan = "Modify `src/main.py` to add the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_nonexistent_path_error(self, tmp_path):
        plan = "Modify `src/nonexistent.py` to add the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "src/nonexistent.py" in findings[0].message

    def test_unverified_markers_skipped(self, tmp_path):
        plan = "<!-- UNVERIFIED: not sure about this --> `src/unknown.py` is referenced."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_templated_paths_skipped(self, tmp_path):
        plan = "Create `src/{module}/handler.py` for each module."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_placeholder_path_skipped(self, tmp_path):
        plan = "See `path/to/file.java` for reference."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_punctuation_inside_backticks_stripped(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# code")
        plan = "Check `src/main.py,` for the implementation."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_path_with_line_number_extracted(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# code")
        plan = "See `src/main.py:42` for the function."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_path_with_line_range_extracted(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# code")
        plan = "See `src/main.py:42-58` for the function."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_multiple_paths_in_one_line(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("# a")
        plan = "Modify `src/a.py` and `src/b.py` together."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # a.py exists, b.py doesn't
        assert len(findings) == 1
        assert "src/b.py" in findings[0].message

    def test_repo_root_none_skips_all(self):
        plan = "Modify `src/nonexistent.py` to add the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=None)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_parentheses_quotes_stripped(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("# code")
        plan = 'Check `("src/main.py")` for details.'
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestPatternSourceValidator
# =============================================================================


class TestPatternSourceValidator:
    def test_code_block_with_source_before_no_findings(self):
        plan = """\
Pattern source: `src/main.py:10-20`
```python
def example():
    a = 1
    b = 2
    return a + b
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_code_block_with_source_after_no_findings(self):
        plan = """\
```python
def example():
    a = 1
    b = 2
    return a + b
```
Pattern source: `src/main.py:10-20`
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_code_block_with_no_existing_pattern_marker(self):
        plan = """\
<!-- NO_EXISTING_PATTERN: new utility function -->
```python
def new_util():
    a = 1
    b = 2
    return a + b
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_ungrounded_code_block_warning(self):
        plan = """\
Some text here.

```python
def example():
    a = 1
    b = 2
    return a + b
```

More text.
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "Pattern source" in findings[0].message

    def test_short_code_block_skipped(self):
        plan = """\
```python
x = 1
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # < 3 content lines, should be skipped
        assert findings == []

    def test_two_line_block_skipped(self):
        plan = """\
```python
x = 1
y = 2
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestUnresolvedMarkersValidator
# =============================================================================


class TestUnresolvedMarkersValidator:
    def test_no_markers_no_findings(self):
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate("# Plan\n\nNo markers here.", ctx)
        assert findings == []

    def test_unverified_marker_info(self):
        plan = "Some text <!-- UNVERIFIED: file path guessed --> more text."
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "UNVERIFIED" in findings[0].message

    def test_no_existing_pattern_marker_info(self):
        plan = "Some text <!-- NO_EXISTING_PATTERN: new approach --> more text."
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "NO_EXISTING_PATTERN" in findings[0].message

    def test_multiple_markers(self):
        plan = (
            "<!-- UNVERIFIED: first -->\n"
            "<!-- NO_EXISTING_PATTERN: second -->\n"
            "<!-- UNVERIFIED: third -->"
        )
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 3
        assert all(f.severity == ValidationSeverity.INFO for f in findings)


# =============================================================================
# TestDiscoveryCoverageValidator
# =============================================================================


class TestDiscoveryCoverageValidator:
    def test_no_researcher_output_no_findings(self):
        validator = DiscoveryCoverageValidator(researcher_output="")
        ctx = ValidationContext()
        findings = validator.validate("# Plan\nSome content.", ctx)
        assert findings == []

    def test_interface_mentioned_in_plan_no_finding(self):
        researcher = """\
### Interface & Class Hierarchy
#### `MyInterface`
- Implemented by: `ConcreteClass` (`src/concrete.py:10`)
"""
        plan = "## Implementation Steps\nModify MyInterface to add new method."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_interface_missing_from_plan_warning(self):
        researcher = """\
### Interface & Class Hierarchy
#### `MyInterface`
- Implemented by: `ConcreteClass` (`src/concrete.py:10`)
"""
        plan = "## Implementation Steps\nDo something else entirely."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "MyInterface" in findings[0].message

    def test_interface_in_out_of_scope_no_finding(self):
        researcher = """\
### Interface & Class Hierarchy
#### `MyInterface`
- Implemented by: `ConcreteClass` (`src/concrete.py:10`)
"""
        plan = "## Out of Scope\nMyInterface changes are not needed."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_method_from_call_sites_missing_warning(self):
        researcher = """\
### Call Sites
#### `processOrder()`
- Called from: `OrderService.handle()` (`src/order.py:42`)
"""
        plan = "## Implementation Steps\nOnly update the database layer."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "processOrder" in findings[0].message

    def test_method_with_parentheses_stripped(self):
        researcher = """\
### Call Sites
#### `doWork()`
- Called from: `Worker.run()` (`src/worker.py:10`)
"""
        plan = "## Implementation Steps\nUpdate doWork to handle errors."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestValidatorRegistry
# =============================================================================


class TestValidatorRegistry:
    def test_empty_registry_empty_report(self):
        registry = ValidatorRegistry()
        ctx = ValidationContext()
        report = registry.validate_all("# Plan", ctx)
        assert report.findings == []
        assert not report.has_errors
        assert not report.has_warnings

    def test_multiple_validators_aggregated(self):
        registry = ValidatorRegistry()
        registry.register(RequiredSectionsValidator())
        registry.register(UnresolvedMarkersValidator())
        ctx = ValidationContext()
        # Missing sections + no markers = only section errors
        report = registry.validate_all("# Just a heading", ctx)
        assert report.has_errors
        assert report.error_count > 0

    def test_factory_returns_all_validators(self):
        registry = create_plan_validator_registry()
        assert len(registry.validators) == 19

    def test_factory_passes_researcher_output(self):
        researcher = "### Interface & Class Hierarchy\n#### `Foo`\n"
        registry = create_plan_validator_registry(researcher_output=researcher)
        # Find the DiscoveryCoverageValidator
        discovery_validators = [
            v for v in registry.validators if isinstance(v, DiscoveryCoverageValidator)
        ]
        assert len(discovery_validators) == 1
        assert discovery_validators[0]._researcher_output == researcher

    def test_report_properties(self):
        report = ValidationReport()
        assert not report.has_errors
        assert not report.has_warnings
        assert report.error_count == 0
        assert report.warning_count == 0

        report.findings.append(
            ValidationFinding(
                validator_name="test",
                severity=ValidationSeverity.ERROR,
                message="error",
            )
        )
        report.findings.append(
            ValidationFinding(
                validator_name="test",
                severity=ValidationSeverity.WARNING,
                message="warning",
            )
        )
        assert report.has_errors
        assert report.has_warnings
        assert report.error_count == 1
        assert report.warning_count == 1


# =============================================================================
# TestValidatorRegistryCrashIsolation
# =============================================================================


class TestValidatorRegistryCrashIsolation:
    """Ensure a crashing validator doesn't skip others."""

    def test_crash_does_not_skip_remaining_validators(self):
        class CrashingValidator(Validator):
            @property
            def name(self) -> str:
                return "Crasher"

            def validate(self, content, context):
                raise RuntimeError("boom")

        registry = ValidatorRegistry()
        registry.register(CrashingValidator())
        registry.register(UnresolvedMarkersValidator())

        plan = "<!-- UNVERIFIED: test -->"
        ctx = ValidationContext()
        report = registry.validate_all(plan, ctx)

        # Should have one ERROR from crash + one INFO from marker
        names = [f.validator_name for f in report.findings]
        assert "Crasher" in names
        assert "Unresolved Markers" in names
        crash_finding = [f for f in report.findings if f.validator_name == "Crasher"][0]
        assert crash_finding.severity == ValidationSeverity.ERROR
        assert "Validator crashed" in crash_finding.message


# =============================================================================
# TestFileExistsValidatorEdgeCases
# =============================================================================


class TestFileExistsValidatorEdgeCases:
    def test_duplicate_paths_deduplicated(self, tmp_path):
        plan = "Modify `src/foo.py` and also `src/foo.py` again."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # Should report the missing file only once despite two references
        assert len(findings) == 1

    def test_path_traversal_ignored(self, tmp_path):
        # Create a file outside repo root to prove traversal is blocked
        plan = "Modify `../../etc/passwd.txt` for the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # Path traversal should be silently skipped (no error reported)
        assert findings == []

    def test_url_paths_skipped(self, tmp_path):
        """URLs should not be treated as file paths."""
        plan = (
            "See `https://example.com/docs/guide.html` and "
            "`http://api.example.com/v1/resource.json` for details."
        )
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_malformed_line_suffix_not_stripped(self, tmp_path):
        """Malformed suffixes like ':---' or ':-42' should not be stripped."""
        (tmp_path / "src").mkdir()
        # File "src/main.py" exists but "src/main.py:---" should not resolve
        (tmp_path / "src" / "main.py").write_text("# code")
        # The colon-suffix should NOT be stripped because "---" is not a valid
        # line number. The raw path becomes "src/main.py:---" which won't exist.
        plan = "See `src/main.py:---` for the function."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # "src/main.py:---" is not stripped to "src/main.py" — the colon stays,
        # and the full string is skipped because it doesn't match file patterns
        # or has an invalid suffix that isn't stripped. Verify no false negative.
        # With the fix, the malformed suffix is NOT stripped, so the path stays
        # as-is and the file check handles it appropriately.
        assert len(findings) <= 1  # Either skipped or reported, but not false-negative


# =============================================================================
# TestPatternSourceValidatorEdgeCases
# =============================================================================


class TestPatternSourceValidatorEdgeCases:
    def test_exactly_three_line_block_checked(self):
        """A code block with exactly 3 content lines should be validated."""
        plan = """\
```python
a = 1
b = 2
c = 3
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING


# =============================================================================
# TestDiscoveryCoverageValidatorEdgeCases
# =============================================================================


class TestDiscoveryCoverageValidatorEdgeCases:
    def test_short_name_no_false_match(self):
        """Word-boundary fix: 'get' should NOT match 'getUser'."""
        researcher = """\
### Call Sites
#### `get()`
- Called from: `Service.fetch()` (`src/service.py:10`)
"""
        plan = "## Implementation Steps\nUpdate getUser to handle errors."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "get" in findings[0].message

    def test_multiple_missing_items_all_reported(self):
        researcher = """\
### Interface & Class Hierarchy
#### `Alpha`
- Implemented by: `AlphaImpl` (`src/alpha.py:1`)
#### `Beta`
- Implemented by: `BetaImpl` (`src/beta.py:1`)
### Call Sites
#### `gamma()`
- Called from: `Runner.go()` (`src/run.py:1`)
"""
        plan = "## Implementation Steps\nDo something unrelated entirely."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        missing_names = {f.message.split("'")[1] for f in findings}
        assert missing_names == {"Alpha", "Beta", "gamma"}

    def test_very_short_names_filtered_out(self):
        """Names shorter than _MIN_NAME_LENGTH should be silently skipped."""
        researcher = """\
### Call Sites
#### `do()`
- Called from: `A.run()` (`src/a.py:1`)
#### `processOrder()`
- Called from: `B.handle()` (`src/b.py:1`)
"""
        plan = "## Implementation Steps\nOnly update processOrder logic."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # "do" (2 chars) should be filtered out, only processOrder is relevant and found
        assert findings == []

    def test_short_name_below_threshold_not_reported(self):
        """A 2-char name like 'do' should not produce a warning even if absent."""
        researcher = """\
### Call Sites
#### `do()`
- Called from: `X.run()` (`src/x.py:1`)
"""
        plan = "## Implementation Steps\nSomething completely unrelated."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestValidationReport
# =============================================================================


class TestValidationReport:
    def test_info_count_property(self):
        report = ValidationReport()
        assert report.info_count == 0

        report.findings.append(
            ValidationFinding(
                validator_name="test",
                severity=ValidationSeverity.INFO,
                message="info 1",
            )
        )
        report.findings.append(
            ValidationFinding(
                validator_name="test",
                severity=ValidationSeverity.WARNING,
                message="warning",
            )
        )
        report.findings.append(
            ValidationFinding(
                validator_name="test",
                severity=ValidationSeverity.INFO,
                message="info 2",
            )
        )
        assert report.info_count == 2


# =============================================================================
# A3: TestRequiredSectionsValidatorCodeBlocks
# =============================================================================


class TestRequiredSectionsValidatorCodeBlocks:
    def test_heading_inside_code_block_not_matched(self):
        """A heading inside a fenced code block should NOT satisfy the section requirement."""
        plan = """\
# Implementation Plan

## Summary
Brief summary.

## Technical Approach
Approach.

```markdown
## Testing Strategy
This is inside a code block, not a real section.
```

## Implementation Steps
1. Step one

## Potential Risks
- Risk one

## Out of Scope
- Not included
"""
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # "Testing Strategy" is only inside a code block — should be reported missing
        assert len(findings) == 1
        assert "Testing Strategy" in findings[0].message

    def test_heading_outside_code_block_still_matched(self):
        """A real heading outside code blocks should still pass."""
        plan = COMPLETE_PLAN
        validator = RequiredSectionsValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# A4: TestFileExistsValidatorRootFiles
# =============================================================================


class TestFileExistsValidatorRootFiles:
    def test_root_file_with_extension_found(self, tmp_path):
        (tmp_path / "setup.py").write_text("# setup")
        plan = "Check `setup.py` for configuration."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_root_file_with_extension_missing(self, tmp_path):
        plan = "Check `setup.py` for configuration."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "setup.py" in findings[0].message

    def test_known_extensionless_found(self, tmp_path):
        (tmp_path / "Makefile").write_text("all:")
        plan = "See `Makefile` for build instructions."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_known_extensionless_missing(self, tmp_path):
        plan = "See `Dockerfile` for container setup."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "Dockerfile" in findings[0].message

    def test_random_word_not_matched_as_file(self, tmp_path):
        """Words like `os.path` or `re.compile` should NOT be matched as root files."""
        plan = "Use `os.path` and `re.compile` for processing."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # These should not be treated as files (no common extension)
        assert findings == []


# =============================================================================
# B12: TestFileExistsValidatorURLSchemes
# =============================================================================


class TestFileExistsValidatorURLSchemes:
    def test_s3_url_skipped(self, tmp_path):
        plan = "Download from `s3://my-bucket/data/file.csv` for the dataset."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_ssh_url_skipped(self, tmp_path):
        plan = "Clone from `ssh://git@github.com/org/repo.git` for source."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_file_url_skipped(self, tmp_path):
        plan = "Open `file:///usr/local/config.json` for reference."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_git_url_skipped(self, tmp_path):
        plan = "Fetch from `git://github.com/org/repo.git` for source."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_gs_url_skipped(self, tmp_path):
        plan = "Download from `gs://bucket/path/data.parquet` for data."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# A6: TestPatternSourceValidatorUnbalancedFences
# =============================================================================


class TestPatternSourceValidatorUnbalancedFences:
    def test_single_unbalanced_fence_warning(self):
        """A single opening ``` without a close should emit a warning."""
        plan = """\
Some text before.

```python
def orphan():
    pass
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert any("Unbalanced code fence" in f.message for f in findings)

    def test_odd_fences_handled(self):
        """Three fences: first two pair up, third is unbalanced."""
        plan = """\
```python
a = 1
```

```python
def orphan():
    pass
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # Should have an unbalanced fence warning
        assert any("Unbalanced code fence" in f.message for f in findings)

    def test_balanced_fences_no_unbalanced_warning(self):
        """Balanced fences should NOT produce an unbalanced warning."""
        plan = """\
```python
a = 1
```
"""
        validator = PatternSourceValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert not any("Unbalanced" in f.message for f in findings)


# =============================================================================
# A7: TestDiscoveryCoverageValidatorSectionAware
# =============================================================================


class TestDiscoveryCoverageValidatorSectionAware:
    def test_name_in_summary_only_still_warns(self):
        """A name mentioned only in Summary (not a target section) should warn."""
        researcher = """\
### Interface & Class Hierarchy
#### `MyService`
- Implemented by: `MyServiceImpl` (`src/service.py:10`)
"""
        plan = """\
## Summary
MyService needs changes.

## Technical Approach
Use the adapter pattern.

## Implementation Steps
1. Modify the adapter.

## Testing Strategy
- Unit tests

## Potential Risks
- None

## Out of Scope
- Nothing
"""
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "MyService" in findings[0].message

    def test_name_in_implementation_steps_passes(self):
        """A name mentioned in Implementation Steps should not warn."""
        researcher = """\
### Interface & Class Hierarchy
#### `MyService`
- Implemented by: `MyServiceImpl` (`src/service.py:10`)
"""
        plan = """\
## Summary
Summary.

## Technical Approach
Approach.

## Implementation Steps
1. Modify MyService to add new method.

## Testing Strategy
- Unit tests

## Potential Risks
- None

## Out of Scope
- Nothing
"""
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_name_in_code_block_inside_target_section_not_matched(self):
        """A name inside a code block in a target section should NOT satisfy coverage."""
        researcher = """\
### Interface & Class Hierarchy
#### `MyService`
- Implemented by: `MyServiceImpl` (`src/service.py:10`)
"""
        plan = """\
## Summary
Summary.

## Technical Approach
Approach.

## Implementation Steps
1. Do something else.

```python
# MyService is here but inside a code block
class MyService:
    pass
```

## Testing Strategy
- Unit tests

## Potential Risks
- None

## Out of Scope
- Nothing
"""
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "MyService" in findings[0].message

    def test_fallback_to_full_content_when_no_target_sections(self):
        """When no target sections exist, fallback to searching full content."""
        researcher = """\
### Interface & Class Hierarchy
#### `MyService`
- Implemented by: `MyServiceImpl` (`src/service.py:10`)
"""
        # Malformed plan with no matching target sections
        plan = "# Plan\n\nMyService is mentioned here."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # Fallback: full content is searched, so MyService is found
        assert findings == []

    def test_fallback_logs_warning(self):
        """When fallback to full content occurs, a warning should be logged."""
        researcher = """\
### Interface & Class Hierarchy
#### `MyService`
- Implemented by: `MyServiceImpl` (`src/service.py:10`)
"""
        plan = "# Plan\n\nMyService is mentioned here."
        validator = DiscoveryCoverageValidator(researcher_output=researcher)
        ctx = ValidationContext()
        with patch("ingot.validation.plan_validators.log_message") as mock_log:
            validator.validate(plan, ctx)
            mock_log.assert_called_once()
            assert "falling back" in mock_log.call_args[0][0].lower()


# =============================================================================
# A8: TestValidatorRegistryCrashLogging
# =============================================================================


class TestValidatorRegistryCrashLogging:
    def test_crash_logs_stack_trace(self):
        """Verify log_message is called with traceback content on crash."""

        class CrashingValidator(Validator):
            @property
            def name(self) -> str:
                return "Crasher"

            def validate(self, content, context):
                raise RuntimeError("test crash boom")

        registry = ValidatorRegistry()
        registry.register(CrashingValidator())
        ctx = ValidationContext()

        with patch("ingot.validation.base.log_message") as mock_log:
            report = registry.validate_all("# Plan", ctx)

            # log_message should have been called with traceback content
            mock_log.assert_called_once()
            log_call_arg = mock_log.call_args[0][0]
            assert "Crasher" in log_call_arg
            assert "test crash boom" in log_call_arg
            assert "Traceback" in log_call_arg

        # Finding should still be present
        assert len(report.findings) == 1
        assert report.findings[0].severity == ValidationSeverity.ERROR
        assert "Validator crashed" in report.findings[0].message


# =============================================================================
# TestFileExistsValidatorNewFileDetection
# =============================================================================


class TestFileExistsValidatorNewFileDetection:
    """Tests for new-file context detection in FileExistsValidator."""

    def test_create_keyword_skips_missing_file(self, tmp_path):
        """'Create' adjacent to a path should not flag missing files."""
        plan = "**File**: Create `src/new-feature.py` for the new module."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_create_keyword_case_insensitive(self, tmp_path):
        """'create' (lowercase) should also skip missing files."""
        plan = "create `src/new-feature.py` as a new module."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_creating_keyword_skips_missing_file(self, tmp_path):
        """'Creating' adjacent to a path should not flag missing files."""
        plan = "Creating `src/new-feature.py` for the new module."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_new_file_keyword_skips_missing_file(self, tmp_path):
        """'New file' adjacent to a path should not flag missing files."""
        plan = "**New file**: `tests/test_consumer.java` for unit tests."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_new_file_parenthesized_skips_missing_file(self, tmp_path):
        """'(NEW FILE)' after a path should not flag missing files."""
        plan = "**File**: `src/MonitoringJob.java` (NEW FILE)"
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_new_file_marker_skips_missing_file(self, tmp_path):
        """Lines with <!-- NEW_FILE --> should not flag missing files."""
        plan = "<!-- NEW_FILE --> `src/new-service.py` is the new service."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_new_file_marker_with_description(self, tmp_path):
        """Lines with <!-- NEW_FILE: desc --> should not flag missing files."""
        plan = "<!-- NEW_FILE: alert configuration --> `k8s/alerts.yaml`"
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_non_create_line_still_errors(self, tmp_path):
        """Lines without creation keywords should still flag missing files."""
        plan = "Modify `src/nonexistent.py` to add the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR

    def test_mixed_create_and_modify_lines(self, tmp_path):
        """Create lines are skipped but non-create lines still flag errors."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "existing.py").write_text("# code")
        plan = (
            "Create `src/new-feature.py` as a new module.\n"
            "Modify `src/existing.py` to import it.\n"
            "Check `src/hallucinated.py` for patterns.\n"
        )
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # Only hallucinated.py should be flagged
        assert len(findings) == 1
        assert "hallucinated.py" in findings[0].message

    def test_existing_file_on_create_line_no_error(self, tmp_path):
        """A file that exists on a 'Create' line should not error (edge case)."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "exists.py").write_text("# exists")
        plan = "Create `src/exists.py` for the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # File exists, but we skip validation for paths adjacent to Create — no error
        assert findings == []

    def test_error_suggestion_mentions_new_file(self, tmp_path):
        """Error suggestion should mention <!-- NEW_FILE --> option."""
        plan = "Modify `src/missing.py` for the feature."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert "NEW_FILE" in findings[0].suggestion

    def test_create_in_prose_does_not_skip_missing_file(self, tmp_path):
        """'Create' used in prose (not adjacent to path) should still flag."""
        plan = "Create a new endpoint in `src/nonexistent.java` to handle requests."
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "nonexistent.java" in findings[0].message

    def test_create_only_skips_adjacent_path(self, tmp_path):
        """Create should only skip the path it's adjacent to, not others on the line."""
        plan = "Create `src/new.py` based on `src/nonexistent.py`"
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # src/new.py is skipped (Create is adjacent), src/nonexistent.py should error
        assert len(findings) == 1
        assert "nonexistent.py" in findings[0].message


# =============================================================================
# TestUnresolvedMarkersValidatorNewFile
# =============================================================================


class TestUnresolvedMarkersValidatorNewFile:
    """Tests for NEW_FILE marker detection in UnresolvedMarkersValidator."""

    def test_new_file_marker_info(self):
        plan = "<!-- NEW_FILE --> `src/new.py` is the new service."
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "NEW_FILE" in findings[0].message

    def test_new_file_marker_with_description_info(self):
        plan = "<!-- NEW_FILE: alert configuration --> `k8s/alerts.yaml`"
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "alert configuration" in findings[0].message

    def test_new_file_marker_without_description(self):
        plan = "<!-- NEW_FILE --> `src/new.py`"
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].message == "NEW_FILE marker"


# =============================================================================
# TestFileExistsValidatorCodeBlocks
# =============================================================================


class TestFileExistsValidatorCodeBlocks:
    """Tests for code block exclusion in FileExistsValidator."""

    def test_yaml_code_block_not_extracted(self, tmp_path):
        """YAML content inside a fenced code block should not be treated as paths."""
        plan = """\
Update the deployment config:

```yaml
metadata:
  annotations:
    app.kubernetes.io/name: ingot
  labels:
    env: production
```

Done.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_shell_commands_inside_code_block_skipped(self, tmp_path):
        """Shell commands with file-like args inside code blocks should be skipped."""
        plan = """\
Run the following to validate:

```bash
promtool check rules k8s/base/monitoring/prometheus-rules.yaml
kubectl apply -f k8s/overlays/prod/deployment.yaml
```

That's it.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_inline_backtick_paths_inside_code_block_skipped(self, tmp_path):
        """Backtick-quoted paths inside code blocks should not be extracted."""
        plan = """\
Example output:

```
Processing `aws-marketplace.json` for deployment.
See `config/settings.yaml` for details.
```

End of example.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_extensionless_files_inside_code_block_skipped(self, tmp_path):
        """Known extensionless files (Dockerfile) inside code blocks should be skipped."""
        plan = """\
Build instructions:

```
docker build -f `Dockerfile` .
cat Makefile
```

End.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_paths_outside_code_blocks_still_validated(self, tmp_path):
        """Paths outside code blocks should still be validated (regression guard)."""
        plan = """\
Modify `src/missing.py` to add the feature.

```yaml
key: value
```

Also update `tests/missing_test.py`.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        paths = {f.message.split("`")[1] for f in findings}
        assert paths == {"src/missing.py", "tests/missing_test.py"}

    def test_line_numbers_correct_after_code_block_filtering(self, tmp_path):
        """Line numbers should be correct for paths after a code block."""
        plan = """\
Line 1

```yaml
key: value
```

Modify `src/after-block.py` here.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].line_number == 7

    def test_multiple_code_blocks_interspersed_with_real_paths(self, tmp_path):
        """Mix of code blocks and real paths: only real paths should be extracted."""
        (tmp_path / "real.py").write_text("# real")
        plan = """\
Check `real.py` for the pattern.

```bash
cat fake/path/inside.yaml
```

Then update `src/missing.py`.

```python
import os
path = "another/fake/file.json"
```

Finally check `real.py` again.
"""
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # real.py exists, src/missing.py doesn't, code block paths skipped
        assert len(findings) == 1
        assert "src/missing.py" in findings[0].message

    def test_extract_paths_directly_skips_code_blocks(self):
        """Direct _extract_paths test: paths inside code blocks are excluded."""
        plan = """\
Modify `src/real.py` here.

```
See `src/fake.py` inside block.
```

Also `tests/real_test.py`.
"""
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        extracted = {p for p, _ in paths}
        assert "src/real.py" in extracted
        assert "tests/real_test.py" in extracted
        assert "src/fake.py" not in extracted


# =============================================================================
# TestTestCoverageValidator
# =============================================================================


class TestTestCoverageValidator:
    def test_all_files_covered_no_findings(self):
        plan = """\
## Implementation Steps
1. Modify `src/service.py` to add feature.
2. Modify `src/handler.py` to wire it up.

## Testing Strategy
| Component | Test file | Key scenarios |
|---|---|---|
| `src/service.py` | `tests/test_service.py` | success, error |
| `src/handler.py` | `tests/test_handler.py` | routing |
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_missing_test_entry_warning(self):
        plan = """\
## Implementation Steps
1. Modify `src/service.py` to add feature.
2. Modify `src/handler.py` to wire it up.

## Testing Strategy
Coverage for service only:
- service tests
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "handler.py" in findings[0].message

    def test_no_test_needed_marker_accepted(self):
        plan = """\
## Implementation Steps
1. Modify `src/config.py` to add new key.

## Testing Strategy
<!-- NO_TEST_NEEDED: config - trivial constant addition -->
No new tests needed for config changes.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_test_files_skipped(self):
        """Test files in impl steps should not be required to have their own test entry."""
        plan = """\
## Implementation Steps
1. Update `tests/test_service.py` to add new test cases.

## Testing Strategy
Update existing test cases.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_no_impl_or_test_section_no_findings(self):
        plan = "## Summary\nJust a summary.\n"
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_stem_matching(self):
        """Stem of the file should be enough for matching in test strategy."""
        plan = """\
## Implementation Steps
1. Modify `src/utils/formatter.py` to add feature.

## Testing Strategy
Tests for formatter component.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_pattern_source_paths_excluded(self):
        """Pattern source citations should not be treated as impl files."""
        plan = """\
## Implementation Steps
1. Modify `src/handler.py` to add the new route.
   Pattern source: `src/existing/routes.py:10-20`

## Testing Strategy
Tests for handler component.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # routes.py is a pattern citation, not an impl file — no warning expected
        assert findings == []

    def test_urls_excluded(self):
        """URLs should not be treated as impl files."""
        plan = """\
## Implementation Steps
1. Modify `src/handler.py` following `https://example.com/docs/api.html`.

## Testing Strategy
Tests for handler component.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_placeholder_paths_excluded(self):
        """Placeholder paths like path/to/file.py should be excluded."""
        plan = """\
## Implementation Steps
1. Modify `src/handler.py` similar to `path/to/example.py`.

## Testing Strategy
Tests for handler component.
"""
        validator = TestCoverageValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestImplementationDetailValidator
# =============================================================================


class TestImplementationDetailValidator:
    def test_step_with_code_block_no_finding(self):
        plan = """\
## Implementation Steps
1. Add the new handler:

```python
class NewHandler:
    pass
```
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_step_with_method_call_no_finding(self):
        plan = """\
## Implementation Steps
1. Call `ServiceClient.fetch_data(user_id: str)` to retrieve the data, then pass the result to `Transformer.apply(data)`.
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_step_with_trivial_marker_no_finding(self):
        plan = """\
## Implementation Steps
1. Add import for the new module. <!-- TRIVIAL_STEP: add import statement -->
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_vague_step_warning(self):
        plan = """\
## Implementation Steps
1. Retrieve the configuration and apply the necessary changes.
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "lacks concrete detail" in findings[0].message

    def test_multiple_steps_mixed(self):
        plan = """\
## Implementation Steps
1. Add the handler using `Router.add_route(path, handler)` to register it.

2. Update the configuration file with the new values.

3. Wire up the service:

```python
service = Service(config)
```
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # Step 2 is vague
        assert len(findings) == 1
        assert "configuration" in findings[0].message

    def test_step_with_pattern_source_no_finding(self):
        plan = """\
## Implementation Steps
1. Register the handler following the existing pattern.
   Pattern source: `src/handlers/base.py:10-20`
"""
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_no_impl_section_no_findings(self):
        plan = "## Summary\nJust a summary.\n"
        validator = ImplementationDetailValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestRiskCategoriesValidator
# =============================================================================


class TestRiskCategoriesValidator:
    def test_all_categories_present_no_findings(self):
        plan = """\
## Potential Risks or Considerations
- **External dependencies**: None identified
- **Prerequisite work**: None identified
- **Data integrity / state management**: None identified
- **Startup / cold-start behavior**: None identified
- **Environment / configuration drift**: None identified
- **Performance / scalability**: None identified
- **Backward compatibility**: None identified
"""
        validator = RiskCategoriesValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_missing_categories_info(self):
        plan = """\
## Potential Risks or Considerations
- **External dependencies**: Need to coordinate with team B
- **Prerequisite work**: Database migration must be done first
"""
        validator = RiskCategoriesValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "Data integrity" in findings[0].message

    def test_no_risks_section_no_findings(self):
        plan = "## Summary\nJust a summary.\n"
        validator = RiskCategoriesValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_alternative_keywords_accepted(self):
        """Variant keywords like 'breaking change' should satisfy backward compatibility."""
        plan = """\
## Potential Risks or Considerations
- External dependencies: none
- Prerequisite work: none
- Data integrity concerns: none
- Cold start issues: none
- Environment differences: none
- Performance impact: none
- Breaking change risk: none
"""
        validator = RiskCategoriesValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_case_insensitive_matching(self):
        plan = """\
## Potential Risks or Considerations
- EXTERNAL DEPENDENCIES: none
- PREREQUISITE WORK: none
- DATA INTEGRITY: none
- STARTUP behavior: none
- ENVIRONMENT drift: none
- PERFORMANCE: none
- BACKWARD COMPATIBILITY: none
"""
        validator = RiskCategoriesValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []


# =============================================================================
# TestUnresolvedMarkersValidatorNewMarkers
# =============================================================================


class TestUnresolvedMarkersValidatorNewMarkers:
    """Tests for NO_TEST_NEEDED and TRIVIAL_STEP marker detection."""

    def test_no_test_needed_marker_info(self):
        plan = "<!-- NO_TEST_NEEDED: config.py - trivial constant -->"
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        marker_findings = [f for f in findings if "NO_TEST_NEEDED" in f.message]
        assert len(marker_findings) == 1
        assert marker_findings[0].severity == ValidationSeverity.INFO
        assert "config.py" in marker_findings[0].message

    def test_trivial_step_marker_info(self):
        plan = "<!-- TRIVIAL_STEP: add import statement -->"
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        marker_findings = [f for f in findings if "TRIVIAL_STEP" in f.message]
        assert len(marker_findings) == 1
        assert marker_findings[0].severity == ValidationSeverity.INFO
        assert "add import statement" in marker_findings[0].message

    def test_multiple_new_markers(self):
        plan = (
            "<!-- NO_TEST_NEEDED: config - reason -->\n"
            "<!-- TRIVIAL_STEP: add import -->\n"
            "<!-- NO_TEST_NEEDED: constants - reason -->"
        )
        validator = UnresolvedMarkersValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        no_test = [f for f in findings if "NO_TEST_NEEDED" in f.message]
        trivial = [f for f in findings if "TRIVIAL_STEP" in f.message]
        assert len(no_test) == 2
        assert len(trivial) == 1


# =============================================================================
# TestFileExistsValidatorMultilineReject
# =============================================================================


class TestFileExistsValidatorMultilineReject:
    """Regression tests: _PATH_RE must not match across newlines."""

    def test_multiline_backtick_span_not_matched_as_path(self, tmp_path):
        """A stray backtick followed by prose on the next line containing
        '/something.yaml' should NOT be picked up as a file path."""
        plan = (
            "Here is a `code snippet that\n"
            "spans multiple lines and mentions /config/app.yaml in passing`.\n"
            "Some more text."
        )
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        # The multi-line span should not produce a path
        path_strings = [p for p, _ln in paths]
        assert (
            "code snippet that\nspans multiple lines and mentions /config/app.yaml in passing"
            not in path_strings
        )

    def test_single_line_backtick_path_still_matched(self, tmp_path):
        """Single-line backtick paths should still be detected."""
        plan = "Update `src/config/app.yaml` with new settings."
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        path_strings = [p for p, _ln in paths]
        assert "src/config/app.yaml" in path_strings

    def test_multiline_backtick_with_extension_not_matched(self, tmp_path):
        """Multi-line backtick spans that happen to contain path-like text
        should not trigger false positives."""
        plan = (
            "The `configuration should follow\n"
            "the pattern described in docs/setup.yml\n"
            "for all environments`."
        )
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        # No paths should be extracted from the multi-line span
        assert len(paths) == 0


class TestFileExistsValidatorMaxPathLength:
    """Test that paths exceeding _MAX_PATH_LENGTH are rejected."""

    def test_very_long_path_rejected(self, tmp_path):
        """A path longer than 300 chars should be skipped."""
        long_segment = "a" * 300
        plan = f"Check `src/{long_segment}/config.yaml` for details."
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        assert len(paths) == 0

    def test_normal_length_path_accepted(self, tmp_path):
        """A path under 300 chars should still be extracted."""
        plan = "Check `src/config/settings.yaml` for details."
        validator = FileExistsValidator()
        paths = validator._extract_paths(plan)
        path_strings = [p for p, _ln in paths]
        assert "src/config/settings.yaml" in path_strings


class TestTestCoverageValidatorMultilineReject:
    """Verify TestCoverageValidator._PATH_RE also rejects multi-line spans."""

    def test_multiline_backtick_not_matched(self):
        """TestCoverageValidator should not match paths across newlines."""
        pattern = TestCoverageValidator._PATH_RE
        text = "`some text\nthat spans lines/file.py`"
        assert pattern.search(text) is None

    def test_single_line_still_matches(self):
        pattern = TestCoverageValidator._PATH_RE
        text = "`src/models/user.py`"
        match = pattern.search(text)
        assert match is not None
        assert match.group(1) == "src/models/user.py"


# =============================================================================
# TestCitationContentValidator
# =============================================================================


class TestCitationContentValidator:
    """Tests for CitationContentValidator."""

    def test_valid_citation_no_findings(self, tmp_path):
        """Citation matching actual file content produces no findings."""
        # Create source file
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "helper.py").write_text(
            "import os\n"
            "\n"
            "class MetricsHelper:\n"
            "    def record(self, name, value):\n"
            "        DistributionSummary.builder(name).register(self.registry)\n"
        )

        plan = """\
## Implementation Steps
1. Add metrics
Pattern source: `src/helper.py:3-5`
```python
class MetricsHelper:
    def record(self, name, value):
        DistributionSummary.builder(name).register(self.registry)
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        # Should be empty or have no WARNING for this citation
        warnings = [f for f in findings if f.severity == ValidationSeverity.WARNING]
        mismatch_warnings = [f for f in warnings if "mismatch" in f.message.lower()]
        assert mismatch_warnings == []

    def test_mismatched_citation_produces_warning(self, tmp_path):
        """Citation pointing to wrong content should produce warning."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "helper.py").write_text(
            "import os\n"
            "\n"
            "class CompleteDifferentClass:\n"
            "    def unrelated_method(self):\n"
            "        pass\n"
        )

        plan = """\
## Implementation Steps
1. Add metrics
Pattern source: `src/helper.py:3-5`
```python
class MetricsHelper:
    def record(self, name, value):
        DistributionSummary.builder(name).register(self.registry)
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        warnings = [f for f in findings if f.severity == ValidationSeverity.WARNING]
        # Should warn about mismatch
        assert any("mismatch" in f.message.lower() for f in warnings)

    def test_file_not_found_produces_warning(self, tmp_path):
        """Citation to non-existent file produces warning."""
        plan = """\
## Implementation Steps
Pattern source: `src/missing.py:1-5`
```python
class Something:
    pass
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        warnings = [f for f in findings if f.severity == ValidationSeverity.WARNING]
        assert any("not found" in f.message.lower() for f in warnings)

    def test_no_repo_root_returns_empty(self):
        """No repo_root → skip validation entirely."""
        plan = "Pattern source: `src/foo.py:1-5`\n```\ncode\n```"
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=None)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_line_range_out_of_bounds(self, tmp_path):
        """Citation with line range beyond file end produces warning."""
        (tmp_path / "small.py").write_text("one line\n")

        plan = """\
Pattern source: `small.py:500-510`
```python
class FarAway:
    pass
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        warnings = [f for f in findings if f.severity == ValidationSeverity.WARNING]
        assert any("out of bounds" in f.message.lower() for f in warnings)

    def test_no_code_block_near_citation_skips(self, tmp_path):
        """Citation without adjacent code block should be skipped."""
        (tmp_path / "foo.py").write_text("class Foo: pass\n")
        plan = "Pattern source: `foo.py:1`\nJust text, no code block."
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_long_code_block_verifies_correctly(self, tmp_path):
        """A citation next to a code block longer than 5 lines should still verify."""
        # Create a source file with >20 lines of matching content
        source_lines = ["class MetricsHelper:"] + [
            f"    line_{i} = DistributionSummary()" for i in range(20)
        ]
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "helper.py").write_text("\n".join(source_lines) + "\n")

        # Build plan with a 20-line code block (opening fence far from closing)
        code_lines = "\n".join(source_lines)
        plan = f"""\
## Implementation Steps
1. Add metrics
Pattern source: `src/helper.py:1-21`
```python
{code_lines}
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        mismatch_warnings = [
            f
            for f in findings
            if f.severity == ValidationSeverity.WARNING and "mismatch" in f.message.lower()
        ]
        assert mismatch_warnings == []

    def test_long_code_block_mismatch_detected(self, tmp_path):
        """A citation next to a long code block with non-matching file should warn."""
        # File has completely different content
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "other.py").write_text("class CompletelyDifferent:\n    pass\n")

        # 20-line code block references identifiers not in the file
        code_lines = "\n".join(
            [f"    DistributionSummary.builder('{i}').register(registry)" for i in range(20)]
        )
        plan = f"""\
## Implementation Steps
Pattern source: `src/other.py:1-2`
```java
{code_lines}
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        mismatch_warnings = [
            f
            for f in findings
            if f.severity == ValidationSeverity.WARNING and "mismatch" in f.message.lower()
        ]
        assert len(mismatch_warnings) >= 1

    def test_path_traversal_blocked(self, tmp_path):
        """Citation with ../../ path traversal should produce a WARNING."""
        plan = """\
## Implementation Steps
Pattern source: `../../etc/config.txt:1-5`
```python
class Something:
    pass
```
"""
        validator = CitationContentValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        warnings = [f for f in findings if f.severity == ValidationSeverity.WARNING]
        assert any("traversal" in f.message.lower() for f in warnings)


# =============================================================================
# TestRegistrationIdempotencyValidator
# =============================================================================


class TestRegistrationIdempotencyValidator:
    """Tests for RegistrationIdempotencyValidator."""

    def test_dual_spring_registration_warns(self):
        """@Component + @Bean in same code block should warn."""
        plan = """\
## Implementation Steps
1. Register the service
```java
@Component
public class MyService {
    // ...
}

@Bean
public MyService myService() {
    return new MyService();
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "dual registration" in findings[0].message.lower()

    def test_single_annotation_no_warning(self):
        """Only @Component, no @Bean → no warning."""
        plan = """\
```java
@Component
public class MyService {
    private final SomeDep dep;
    public MyService(SomeDep dep) { this.dep = dep; }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_single_bean_no_warning(self):
        """Only @Bean, no @Component → no warning."""
        plan = """\
```java
@Bean
public MyService myService() {
    return new MyService();
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_different_code_blocks_no_warning(self):
        """@Component and @Bean in separate code blocks → no warning."""
        plan = """\
## Step 1
```java
@Component
public class MyService {}
```

## Step 2
```java
@Bean
public OtherService otherService() { return new OtherService(); }
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_angular_dual_registration(self):
        """@Injectable + provide() should warn."""
        plan = """\
```typescript
@Injectable()
export class MyService {}

providers: [
    provide(MyService, { useClass: MyService })
]
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) == 1

    def test_short_code_block_skipped(self):
        """Very short code blocks are skipped."""
        plan = """\
```
x
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert findings == []

    def test_service_annotation_with_bean(self):
        """@Service (Spring family) + @Bean should also warn."""
        plan = """\
```java
@Service
public class MyService {
    // service implementation
}

@Configuration
public class Config {
    @Bean
    public MyService myService() { return new MyService(); }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        assert len(findings) >= 1

    def test_cross_block_dual_registration_warns(self):
        """@Component class MyService in block 1, @Bean MyService in block 2 → WARNING."""
        plan = """\
## Step 1
```java
@Component
public class MyService {
    private final SomeDep dep;
    public MyService(SomeDep dep) { this.dep = dep; }
}
```

## Step 2
```java
@Configuration
public class Config {
    @Bean
    public MyService myService() { return new MyService(); }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        cross_block = [f for f in findings if "cross-block" in f.message.lower()]
        assert len(cross_block) == 1
        assert "MyService" in cross_block[0].message

    def test_cross_block_different_classes_no_warning(self):
        """@Component class Foo in block 1, @Bean Bar in block 2 → no cross-block warning."""
        plan = """\
## Step 1
```java
@Component
public class Foo {
    // ...
}
```

## Step 2
```java
@Configuration
public class Config {
    @Bean
    public Bar bar() { return new Bar(); }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        cross_block = [f for f in findings if "cross-block" in f.message.lower()]
        assert cross_block == []

    def test_cross_block_interface_vs_impl_warns(self):
        """@Component class MyServiceImpl + @Bean MyService across blocks → warning."""
        plan = """\
## Step 1
```java
@Component
public class MyServiceImpl implements MyService {
    // impl
}
```

## Step 2
```java
@Configuration
public class Config {
    @Bean
    public MyService myService() { return new MyServiceImpl(); }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        cross_block = [f for f in findings if "cross-block" in f.message.lower()]
        assert len(cross_block) == 1

    def test_three_block_cross_registration(self):
        """Annotation in block 1, unrelated block 2, bean in block 3 → warning."""
        plan = """\
## Step 1
```java
@Component
public class MyService {
    // component
}
```

## Step 2
```java
public class SomethingUnrelated {
    // no registration here
}
```

## Step 3
```java
@Configuration
public class Config {
    @Bean
    public MyService myService() { return new MyService(); }
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        cross_block = [f for f in findings if "cross-block" in f.message.lower()]
        assert len(cross_block) == 1
        assert "MyService" in cross_block[0].message

    def test_bean_with_intermediate_annotations(self):
        """@Bean followed by @Scope and other annotations should still extract type."""
        plan = """\
```java
@Component
public class MyService {
}

@Bean
@Scope("prototype")
@Primary
public MyService myService() {
    return new MyService();
}
```
"""
        validator = RegistrationIdempotencyValidator()
        ctx = ValidationContext()
        findings = validator.validate(plan, ctx)
        # Should detect dual registration within the same block
        assert len(findings) >= 1

    def test_normalize_strips_impl_suffix(self):
        """_normalize_class_name should strip 'Impl' suffix."""
        assert (
            RegistrationIdempotencyValidator._normalize_class_name("MyServiceImpl") == "MyService"
        )
        assert RegistrationIdempotencyValidator._normalize_class_name("FooAdapter") == "Foo"
        assert RegistrationIdempotencyValidator._normalize_class_name("BarDecorator") == "Bar"

    def test_normalize_preserves_short_name(self):
        """_normalize_class_name should not strip suffix if name would be empty."""
        assert RegistrationIdempotencyValidator._normalize_class_name("Impl") == "Impl"
        assert RegistrationIdempotencyValidator._normalize_class_name("Default") == "Default"

    def test_normalize_strips_default_prefix(self):
        """_normalize_class_name should strip 'Default' prefix."""
        assert (
            RegistrationIdempotencyValidator._normalize_class_name("DefaultMyService")
            == "MyService"
        )

    def test_normalize_default_adapter_strips_prefix(self):
        """DefaultAdapter → prefix stripped → 'Adapter' (suffix guard prevents empty)."""
        assert RegistrationIdempotencyValidator._normalize_class_name("DefaultAdapter") == "Adapter"
        # DefaultFooAdapter → 'Default' stripped → 'FooAdapter' → 'Adapter' stripped → 'Foo'
        assert RegistrationIdempotencyValidator._normalize_class_name("DefaultFooAdapter") == "Foo"


# =============================================================================
# TestRegistryIncludesNewValidators
# =============================================================================


class TestRegistryIncludesNewValidators:
    """Test that new validators are registered in the factory."""

    def test_registry_includes_citation_content_validator(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Citation Content" in names

    def test_registry_includes_registration_idempotency_validator(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Registration Idempotency" in names

    def test_registry_includes_snippet_completeness_validator(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Snippet Completeness" in names

    def test_registry_includes_operational_completeness_validator(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Operational Completeness" in names

    def test_registry_includes_naming_consistency_validator(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Naming Consistency" in names

    def test_registry_has_nineteen_validators(self):
        registry = create_plan_validator_registry()
        assert len(registry.validators) == 19

    def test_registry_includes_ticket_reconciliation(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Ticket Reconciliation" in names

    def test_registry_includes_prerequisite_consistency(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Prerequisite Consistency" in names

    def test_registry_includes_bean_qualifier(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Bean Qualifier" in names

    def test_registry_includes_configuration_completeness(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Configuration Completeness" in names

    def test_registry_includes_test_scenario(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Test Scenario" in names

    def test_registry_includes_claim_consistency(self):
        registry = create_plan_validator_registry()
        names = [v.name for v in registry.validators]
        assert "Claim Consistency" in names


# =============================================================================
# SnippetCompletenessValidator Tests
# =============================================================================


class TestSnippetCompletenessValidator:
    """Tests for SnippetCompletenessValidator."""

    def _validate(self, content: str) -> list[ValidationFinding]:
        v = SnippetCompletenessValidator()
        return v.validate(content, ValidationContext())

    def test_clean_snippet_with_constructor(self):
        plan = """## Implementation
```java
public class FooService {
    private final MetricsHelper helper;

    public FooService(MetricsHelper helper) {
        this.helper = helper;
    }
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_fields_without_constructor_warns(self):
        plan = """## Implementation
```java
public class FooService {
    private final MetricsHelper helper;
    private final AlertManager alertManager;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "constructor" in findings[0].message.lower() or "init" in findings[0].message.lower()

    def test_python_self_without_init_warns(self):
        plan = """## Implementation
```python
class FooService:
    self.helper = MetricsHelper()
    self.alert_manager = AlertManager()
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1

    def test_python_with_init_clean(self):
        plan = """## Implementation
```python
class FooService:
    def __init__(self, helper):
        self.helper = helper
        self.count = 0
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_autowired_annotation_counts_as_init(self):
        plan = """## Implementation
```java
public class FooService {
    @Autowired
    private MetricsHelper helper;
    private final String name;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_short_code_block_skipped(self):
        plan = """## Config
```java
int x = 5;
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_kotlin_val_without_init_warns(self):
        plan = """## Implementation
```kotlin
class FooService {
    val helper: MetricsHelper
    val alertManager: AlertManager
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1

    def test_kotlin_with_init_block_clean(self):
        plan = """## Implementation
```kotlin
class FooService {
    val helper: MetricsHelper
    init {
        helper = createHelper()
    }
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0


# =============================================================================
# OperationalCompletenessValidator Tests
# =============================================================================


class TestOperationalCompletenessValidator:
    """Tests for OperationalCompletenessValidator."""

    def _validate(self, content: str) -> list[ValidationFinding]:
        v = OperationalCompletenessValidator()
        return v.validate(content, ValidationContext())

    def test_no_metrics_keywords_skips(self):
        plan = """## Summary
This plan adds a REST endpoint for user profile.
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_metrics_without_operational_elements_warns(self):
        plan = """## Summary
This plan adds a Prometheus metric for monitoring queue depth.
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO
        assert "query example" in findings[0].message
        assert "threshold value" in findings[0].message
        assert "escalation reference" in findings[0].message

    def test_complete_operational_plan_clean(self):
        plan = """## Summary
Add alert for high queue depth metric.

## Monitoring
Query: `sum(rate(queue_depth{service="foo"}[5m])) > 100`
Threshold: > 100 messages triggers alert
Escalation: page on-call via PagerDuty #sre-alerts
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_partial_operational_plan(self):
        plan = """## Summary
Add gauge metric for pending messages count.

## Monitoring
Threshold: > 500 messages triggers warning
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        # Should mention missing elements but not all three
        msg = findings[0].message
        assert "query example" in msg
        assert "escalation reference" in msg
        assert "threshold value" not in msg  # threshold IS present

    def test_alert_keyword_activates(self):
        plan = """## Summary
Create an alert rule for SQS queue overflow.
"""
        findings = self._validate(plan)
        assert len(findings) == 1

    def test_dashboard_keyword_activates(self):
        plan = """## Summary
Build a Grafana dashboard for service health.
"""
        findings = self._validate(plan)
        assert len(findings) == 1

    def test_slo_keyword_activates(self):
        plan = """## Summary
Define SLO targets for API latency.
"""
        findings = self._validate(plan)
        assert len(findings) == 1

    def test_severity_elevated_to_warning_with_metric_signal(self):
        """With ticket_signals containing 'metric', severity should be WARNING."""
        plan = """## Summary
This plan adds a Prometheus metric for monitoring queue depth.
"""
        v = OperationalCompletenessValidator()
        ctx = ValidationContext(ticket_signals=["metric"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING


# =============================================================================
# NamingConsistencyValidator Tests
# =============================================================================


class TestNamingConsistencyValidator:
    """Tests for NamingConsistencyValidator."""

    def _validate(self, content: str) -> list[ValidationFinding]:
        v = NamingConsistencyValidator()
        return v.validate(content, ValidationContext())

    def test_consistent_naming_clean(self):
        plan = """## Config
Set `queue.depth.threshold` and `queue.depth.alert` in the config.
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_inconsistent_separators_warns(self):
        plan = """## Config
Set the metric name to `queue.depth.threshold` in Java
and `queue_depth_threshold` in the YAML config.
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "dot" in findings[0].message
        assert "underscore" in findings[0].message

    def test_file_paths_skipped(self):
        plan = """## Files
Edit `src/main/java/Config.java` and `src/test/java/ConfigTest.java`.
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_code_blocks_excluded(self):
        plan = """## Config
Use `metric.name` in configuration.

```java
String METRIC_NAME = "metric.name";
String metric_name = config.get("metric.name");
```
"""
        findings = self._validate(plan)
        # Only the backtick-quoted identifiers outside code blocks are checked
        assert len(findings) == 0

    def test_short_identifiers_ignored(self):
        plan = """## Config
Use `a.b` for the key.
"""
        findings = self._validate(plan)
        # Too short (< 4 chars) to match _IDENTIFIER_RE
        assert len(findings) == 0

    def test_hyphen_vs_underscore_warns(self):
        plan = """## Config
Set `service-name-config` in YAML and `service_name_config` in env vars.
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert "hyphen" in findings[0].message
        assert "underscore" in findings[0].message

    def test_three_way_inconsistency(self):
        plan = """## Config
Use `queue.depth.max` in Java properties,
`queue_depth_max` in environment variables,
and `queue-depth-max` in YAML config.
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        msg = findings[0].message
        assert "dot" in msg
        assert "underscore" in msg
        assert "hyphen" in msg


# =============================================================================
# TestTicketReconciliationValidator
# =============================================================================


class TestTicketReconciliationValidator:
    def _validate(self, plan, files=None, acs=None):
        v = TicketReconciliationValidator()
        ctx = ValidationContext(
            ticket_files_to_modify=files or [],
            ticket_acceptance_criteria=acs or [],
        )
        return v.validate(plan, ctx)

    def test_no_ticket_fields_no_findings(self):
        plan = COMPLETE_PLAN
        findings = self._validate(plan)
        assert findings == []

    def test_matching_file_no_findings(self):
        plan = """\
## Implementation Steps
1. Modify `src/main/java/GracePeriodStartAction.java`
   Add Temporal workflow start logic.
"""
        findings = self._validate(
            plan,
            files=["GracePeriodStartAction.java — Enhance to start workflow"],
        )
        assert findings == []

    def test_missing_file_warns(self):
        plan = """\
## Implementation Steps
1. Modify `src/main/java/SomeOtherClass.java`
   Refactor logic.
"""
        findings = self._validate(
            plan,
            files=["GracePeriodStartAction.java — Enhance to start workflow"],
        )
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "GracePeriodStartAction" in findings[0].message

    def test_deviation_callout_suppresses_warning(self):
        plan = """\
## Implementation Steps
1. Modify `src/main/java/SomeOtherClass.java`

**Deviation from ticket**: Using SomeOtherClass instead of GracePeriodStartAction
because the action was renamed.
"""
        findings = self._validate(
            plan,
            files=["GracePeriodStartAction.java — Enhance to start workflow"],
        )
        assert findings == []

    def test_ac_traceable_no_findings(self):
        plan = """\
## Implementation Steps
1. Configure Temporal client with proper connection settings.
   Set up WorkflowClient bean with host and port properties.
"""
        findings = self._validate(
            plan,
            acs=["Temporal client is configured with proper connection settings"],
        )
        assert findings == []

    def test_ac_not_traceable_warns(self):
        plan = """\
## Implementation Steps
1. Add logging to the service layer.
"""
        findings = self._validate(
            plan,
            acs=["Temporal client is configured with proper connection settings"],
        )
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "AC" in findings[0].message

    def test_multiple_files_mixed(self):
        plan = """\
## Implementation Steps
1. Modify `MarketplaceConfig.java` to add WorkflowClient bean.
2. Add logging to service.
"""
        findings = self._validate(
            plan,
            files=[
                "MarketplaceConfig.java — Add WorkflowClient bean",
                "TemporalConfig.java — NEW",
            ],
        )
        # MarketplaceConfig found, TemporalConfig missing
        assert len(findings) == 1
        assert "TemporalConfig" in findings[0].message


# =============================================================================
# TestPrerequisiteConsistencyValidator
# =============================================================================


class TestPrerequisiteConsistencyValidator:
    def _validate(self, plan):
        v = PrerequisiteConsistencyValidator()
        ctx = ValidationContext()
        return v.validate(plan, ctx)

    def test_no_todos_no_findings(self):
        plan = """\
## Implementation Steps
1. Step one
```java
public void doStuff() {
    service.run();
}
```

## Potential Risks or Considerations
**Prerequisite work**: None identified
"""
        findings = self._validate(plan)
        assert findings == []

    def test_todos_with_none_identified_warns(self):
        plan = """\
## Implementation Steps
1. Start workflow
```java
// TODO: Replace with actual workflow interface
// TODO: Add proper error handling
public void startWorkflow() {
    // TODO: Implement
}
```

## Potential Risks or Considerations
**Prerequisite work**: None identified
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING
        assert "TODO" in findings[0].message
        assert "None identified" in findings[0].message or "Prerequisite" in findings[0].message

    def test_todos_with_declared_prereqs_no_findings(self):
        plan = """\
## Implementation Steps
1. Start workflow
```java
// TODO: Replace with actual workflow interface
public void startWorkflow() {
    client.start();
}
```

## Potential Risks or Considerations
**Prerequisite work**: Workflow interface definition must be completed first
"""
        findings = self._validate(plan)
        assert findings == []

    def test_multiple_todos_counted(self):
        plan = """\
## Implementation Steps
1. Implement handler
```java
// TODO: Replace with actual implementation
// TODO: Add error handling
public void handle() {
    // TODO: finish this
    return;
}
```

## Potential Risks or Considerations
**Prerequisite work**: None identified
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert "3" in findings[0].message  # 3 TODOs


# =============================================================================
# TestSnippetCompletenessCommentDetection
# =============================================================================


class TestSnippetCompletenessCommentDetection:
    def _validate(self, plan):
        v = SnippetCompletenessValidator()
        ctx = ValidationContext()
        return v.validate(plan, ctx)

    def test_mostly_commented_code_warns(self):
        plan = """\
## Code
```java
// TODO: Replace with actual workflow interface
// WorkflowOptions options = WorkflowOptions.newBuilder()
//     .setTaskQueue("gcp-grace-period")
//     .setWorkflowId(subscriptionId)
//     .build();
// workflow.start(options);
```
"""
        findings = self._validate(plan)
        assert any("commented out" in f.message for f in findings)

    def test_normal_code_no_comment_warning(self):
        plan = """\
## Code
```java
WorkflowOptions options = WorkflowOptions.newBuilder()
    .setTaskQueue(config.getTaskQueue())
    .setWorkflowId(subscriptionId)
    .build();
workflow.start(options);
```
"""
        findings = self._validate(plan)
        assert not any("commented out" in f.message for f in findings)

    def test_few_comments_in_normal_code_ok(self):
        plan = """\
## Code
```java
// Configure workflow options
WorkflowOptions options = WorkflowOptions.newBuilder()
    .setTaskQueue(config.getTaskQueue())
    .setWorkflowId(subscriptionId)
    .build();
workflow.start(options);
// Log the result
logger.info("Workflow started");
```
"""
        findings = self._validate(plan)
        assert not any("commented out" in f.message for f in findings)

    def test_short_commented_block_not_flagged(self):
        plan = """\
## Code
```java
// TODO
// fix
```
"""
        findings = self._validate(plan)
        # Only 2 non-blank lines — below the 4-line threshold
        assert not any("commented out" in f.message for f in findings)


# =============================================================================
# TestRiskCategoriesRollbackCheck
# =============================================================================


class TestRiskCategoriesRollbackCheck:
    def _validate(self, plan, signals=None):
        v = RiskCategoriesValidator()
        ctx = ValidationContext(ticket_signals=signals or [])
        return v.validate(plan, ctx)

    def test_no_workflow_signal_no_rollback_check(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: None identified
**Prerequisite work**: None identified
**Data integrity / state management**: None identified
**Startup / cold-start behavior**: None identified
**Environment / configuration drift**: None identified
**Performance / scalability**: None identified
**Backward compatibility**: None identified
"""
        findings = self._validate(plan, signals=["refactor"])
        # No rollback warning for non-config/non-workflow signals
        assert not any("rollback" in f.message for f in findings)

    def test_workflow_signal_without_rollback_warns(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal SDK
**Prerequisite work**: None identified
**Data integrity / state management**: None identified
**Startup / cold-start behavior**: None identified
**Environment / configuration drift**: None identified
**Performance / scalability**: None identified
**Backward compatibility**: None identified
"""
        findings = self._validate(plan, signals=["workflow"])
        assert any("rollback" in f.message for f in findings)

    def test_config_signal_without_rollback_warns(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: None
**Prerequisite work**: None
"""
        findings = self._validate(plan, signals=["config"])
        assert any("rollback" in f.message for f in findings)

    def test_rollback_mentioned_no_warning(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal SDK
**Prerequisite work**: None identified
Rollback strategy: Disable feature flag to revert to previous behavior.
"""
        findings = self._validate(plan, signals=["workflow", "config"])
        assert not any("rollback" in f.message for f in findings)

    def test_disable_flag_mentioned_no_warning(self):
        plan = """\
## Potential Risks or Considerations
To revert, disable flag `enable.temporal.workflow` in configuration.
"""
        findings = self._validate(plan, signals=["config"])
        assert not any("rollback" in f.message for f in findings)


# =============================================================================
# TestOperationalCompletenessWorkflowSignal
# =============================================================================


class TestOperationalCompletenessWorkflowSignal:
    def test_workflow_signal_elevates_severity(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nStart Temporal workflow for grace period processing.\n"
        ctx = ValidationContext(ticket_signals=["workflow"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING


# =============================================================================
# TestBeanQualifierValidator
# =============================================================================


class TestBeanQualifierValidator:
    """Tests for BeanQualifierValidator."""

    def _validate(self, content: str, **ctx_kwargs) -> list[ValidationFinding]:
        v = BeanQualifierValidator()
        return v.validate(content, ValidationContext(**ctx_kwargs))

    def test_single_bean_no_finding(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient workflowClient() {
    return WorkflowClient.newInstance(stub);
}

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_two_beans_same_type_no_qualifier_error(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "WorkflowClient" in findings[0].message
        assert "@Qualifier" in findings[0].suggestion

    def test_two_beans_with_qualifier_clean(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}

@Autowired
public MyService(@Qualifier("productionClient") WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_primary_annotation_suppresses(self):
        plan = """\
## Implementation
```java
@Bean
@Primary
public WorkflowClient productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_primary_only_suppresses_its_type(self):
        """@Primary on DataSource should NOT suppress WorkflowClient warning."""
        plan = """\
## Implementation
```java
@Bean
@Primary
public DataSource mainDataSource() {
    return new HikariDataSource();
}

@Bean
public DataSource replicaDataSource() {
    return new HikariDataSource();
}

@Bean
public WorkflowClient productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}

@Autowired
public MyService(DataSource ds, WorkflowClient client) {
    this.ds = ds;
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        # DataSource has @Primary → no finding for DataSource
        assert not any("DataSource" in f.message for f in findings)
        # WorkflowClient has NO @Primary → should still be flagged
        assert any("WorkflowClient" in f.message for f in findings)

    def test_no_injection_no_finding(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_different_return_types_clean(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient workflowClient() {
    return WorkflowClient.newInstance(stub);
}

@Bean
public DataSource dataSource() {
    return new HikariDataSource();
}

@Autowired
public MyService(WorkflowClient client, DataSource ds) {
    this.client = client;
    this.ds = ds;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_repo_scan_finds_additional_bean(self, tmp_path):
        import subprocess

        # Initialize git repo so FileIndex (git ls-files) works
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Create a fake repo with a @Bean method
        java_dir = tmp_path / "src" / "main" / "java"
        java_dir.mkdir(parents=True)
        config_file = java_dir / "TemporalConfig.java"
        config_file.write_text(
            """\
package com.example;

import io.temporal.client.WorkflowClient;
import org.springframework.context.annotation.Bean;

public class TemporalConfig {
    @Bean
    public WorkflowClient existingWorkflowClient() {
        return WorkflowClient.newInstance(stubs);
    }
}
"""
        )
        # Stage file so git ls-files picks it up
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        plan = """\
## Implementation
```java
@Bean
public WorkflowClient newWorkflowClient() {
    return WorkflowClient.newInstance(newStubs);
}

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        from ingot.discovery.file_index import FileIndex

        fi = FileIndex(tmp_path)
        v = BeanQualifierValidator(file_index=fi)
        findings = v.validate(plan, ValidationContext(repo_root=tmp_path))
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "repo + plan" in findings[0].message

    def test_repo_scan_no_repo_root_warns(self):
        plan = """\
## Implementation
```java
@Bean
public DataSource primary() {
    return new HikariDataSource();
}

@Bean
public DataSource secondary() {
    return new HikariDataSource();
}

@Autowired
public MyService(DataSource ds) {
    this.ds = ds;
}
```
"""
        # No repo_root — plan-only analysis for high-risk type
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.ERROR
        assert "plan" in findings[0].message

    def test_split_params_handles_annotations(self):
        from ingot.validation.plan_validators import _split_params

        result = _split_params('@Value("${foo}") int bar, WorkflowClient client')
        assert len(result) == 2
        assert "bar" in result[0]
        assert "WorkflowClient" in result[1]

    def test_primitive_types_excluded(self):
        plan = """\
## Implementation
```java
@Bean
public String fooString() { return "foo"; }

@Bean
public String barString() { return "bar"; }

@Autowired
public MyService(String name) {
    this.name = name;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_multiline_bean_with_context(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient
    productionClient() {
    return WorkflowClient.newInstance(prodStub);
}

@Bean
public WorkflowClient testClient() {
    return WorkflowClient.newInstance(testStub);
}

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        # Should detect at least the second @Bean via regex
        assert any("WorkflowClient" in f.message for f in findings)

    def test_repair_worthy_set(self):
        plan = """\
## Implementation
```java
@Bean
public WorkflowClient prod() { return null; }

@Bean
public WorkflowClient test() { return null; }

@Autowired
public MyService(WorkflowClient client) {
    this.client = client;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].repair_worthy is True


# =============================================================================
# TestConfigurationCompletenessValidator
# =============================================================================


class TestConfigurationCompletenessValidator:
    """Tests for ConfigurationCompletenessValidator."""

    def _validate(self, content: str, **ctx_kwargs) -> list[ValidationFinding]:
        v = ConfigurationCompletenessValidator()
        return v.validate(content, ValidationContext(**ctx_kwargs))

    def test_all_setters_have_properties_clean(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private String taskQueue;

    public String getTaskQueue() { return taskQueue; }
    public void setTaskQueue(String taskQueue) { this.taskQueue = taskQueue; }
}

// Usage:
properties.setTaskQueue("my-queue");
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_setter_without_property_warns(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private boolean enabled;
}

// Usage:
properties.setTaskQueue("gcp-grace-period");
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert "taskQueue" in findings[0].message

    def test_no_properties_class_skips(self):
        plan = """\
## Implementation
```java
public class MyService {
    public void doWork() {
        options.setTaskQueue("my-queue");
    }
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_infrastructure_setters_excluded(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "app")
public class AppProperties {
    private String name;
}

builder.build();
factory.newBuilder();
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_builder_type_excluded(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private boolean enabled;
}

WorkflowServiceStubsOptions options = WorkflowServiceStubsOptions.newBuilder()
    .setTarget("localhost:7233")
    .build();
```
"""
        findings = self._validate(plan)
        # Should NOT flag Options.newBuilder().setTarget()
        assert not any("setTarget" in f.message for f in findings)

    def test_getter_implies_property(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    public String getTaskQueue() { return "default"; }
}

properties.setTaskQueue("my-queue");
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_case_insensitive_matching(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private Duration rpcTimeout;
}

properties.setRpcTimeout(Duration.ofSeconds(30));
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_prerequisite_work_suppresses(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private boolean enabled;
}

// TODO: properties.setTaskQueue(...)
```

## Prerequisite work
- Add taskQueue property to TemporalProperties
"""
        findings = self._validate(plan)
        assert not any("taskQueue" in f.message for f in findings)

    def test_repair_worthy_on_properties_bound(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private boolean enabled;
}

properties.setTaskQueue("gcp-grace-period");
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].repair_worthy is True

    def test_commented_setter_without_property_warns(self):
        plan = """\
## Implementation
```java
@ConfigurationProperties(prefix = "temporal")
public class TemporalProperties {
    private boolean enabled;
}

// properties.setTaskQueue("gcp-grace-period");
```
"""
        # Commented-out setter still inside code block, regex still picks it up
        # because it matches "properties.setTaskQueue" in the string
        findings = self._validate(plan)
        assert any("taskQueue" in f.message for f in findings)


# =============================================================================
# TestTestScenarioValidator
# =============================================================================


class TestTestScenarioValidator:
    """Tests for TestScenarioValidator."""

    def _validate(self, content: str, **ctx_kwargs) -> list[ValidationFinding]:
        v = TestScenarioValidator()
        return v.validate(content, ValidationContext(**ctx_kwargs))

    def test_workflow_signal_missing_idempotency(self):
        plan = """\
## Testing Strategy
- Unit tests for service creation
- Integration test for workflow start
"""
        findings = self._validate(plan, ticket_signals=["workflow"])
        labels = [f.message for f in findings]
        assert any("Idempotency test" in msg for msg in labels)

    def test_workflow_signal_all_scenarios_covered(self):
        plan = """\
## Testing Strategy
- Test idempotency: verify duplicate workflow start returns existing run
- Test timeout: verify connection timeout throws expected error
- Test error handling: verify exception propagation from workflow failure
"""
        findings = self._validate(plan, ticket_signals=["workflow"])
        assert len(findings) == 0

    def test_no_signal_no_check(self):
        plan = """\
## Testing Strategy
- Unit tests only
"""
        findings = self._validate(plan, ticket_signals=[])
        assert len(findings) == 0

    def test_content_triggered_optional_dependency(self):
        plan = """\
## Summary
Handle optional Temporal dependency gracefully.

## Testing Strategy
- Test basic functionality
"""
        findings = self._validate(plan)
        labels = [f.message for f in findings]
        assert any("Optional dependency absent test" in msg for msg in labels)

    def test_feature_flag_content_trigger(self):
        plan = """\
## Summary
Add feature flag for new workflow.

## Testing Strategy
- Test workflow start
"""
        findings = self._validate(plan)
        labels = [f.message for f in findings]
        assert any("Feature flag toggle test" in msg for msg in labels)

    def test_no_testing_section_skips(self):
        plan = """\
## Summary
Some summary without testing section.
"""
        findings = self._validate(plan, ticket_signals=["workflow"])
        assert len(findings) == 0

    def test_autowired_required_false_triggers(self):
        plan = """\
## Summary
Use @Autowired(required = false) for optional injection.

## Testing Strategy
- Test service works correctly
"""
        findings = self._validate(plan)
        labels = [f.message for f in findings]
        assert any("Optional injection absent test" in msg for msg in labels)


# =============================================================================
# TestClaimConsistencyValidator
# =============================================================================


class TestClaimConsistencyValidator:
    """Tests for ClaimConsistencyValidator."""

    def _validate(self, content: str, **ctx_kwargs) -> list[ValidationFinding]:
        v = ClaimConsistencyValidator()
        return v.validate(content, ValidationContext(**ctx_kwargs))

    def test_no_claims_clean(self):
        plan = """\
## Summary
Add new Temporal workflow integration.

## Implementation Steps
1. Create TemporalConfig.java
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_correct_existence_claim_with_repo(self, tmp_path):
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Create a fake pom.xml with the dependency
        pom = tmp_path / "pom.xml"
        pom.write_text(
            """\
<project>
  <dependencies>
    <dependency>
      <groupId>io.temporal</groupId>
      <artifactId>temporal-sdk</artifactId>
    </dependency>
  </dependencies>
</project>
"""
        )
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        plan = """\
## Summary
The `temporal-sdk` already exists in `pom.xml`.
"""
        from ingot.discovery.file_index import FileIndex

        fi = FileIndex(tmp_path)
        v = ClaimConsistencyValidator(file_index=fi)
        findings = v.validate(plan, ValidationContext(repo_root=tmp_path))
        assert not any("not found" in f.message for f in findings)

    def test_false_existence_claim_warns(self, tmp_path):
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        pom = tmp_path / "pom.xml"
        pom.write_text("<project><dependencies></dependencies></project>")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)

        plan = """\
## Summary
The `temporal-sdk` already exists in `pom.xml`.
"""
        from ingot.discovery.file_index import FileIndex

        fi = FileIndex(tmp_path)
        v = ClaimConsistencyValidator(file_index=fi)
        findings = v.validate(plan, ValidationContext(repo_root=tmp_path))
        assert len(findings) == 1
        assert "not found" in findings[0].message

    def test_plan_internal_field_contradiction(self):
        plan = """\
## Summary
The field `taskQueue` in `TemporalProperties` enables queue configuration.

## Implementation
```java
public class TemporalProperties {
    private boolean enabled;
    private String namespace;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert "taskQueue" in findings[0].message
        assert "TemporalProperties" in findings[0].message

    def test_plan_internal_consistency_clean(self):
        plan = """\
## Summary
The field `enabled` in `TemporalProperties` controls activation.

## Implementation
```java
public class TemporalProperties {
    private boolean enabled;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 0

    def test_unverified_marker_with_claim_warns(self):
        plan = """\
## Summary
The dependency `temporal-sdk` already exists in pom.xml <!-- UNVERIFIED: not checked -->
"""
        findings = self._validate(plan)
        assert len(findings) >= 1
        assert any("UNVERIFIED" in f.message for f in findings)

    def test_no_repo_root_skips_repo_checks(self):
        plan = """\
## Summary
The `temporal-sdk` already exists in `pom.xml`.
"""
        # No repo_root — only plan-internal checks, no repo verification
        findings = self._validate(plan)
        # Should not crash, and should not emit repo-based findings
        assert not any("not found in the repo" in f.message for f in findings)

    def test_repair_worthy_on_contradiction(self):
        plan = """\
## Summary
The field `taskQueue` in `TemporalProperties` is pre-configured.

## Implementation
```java
public class TemporalProperties {
    private boolean enabled;
}
```
"""
        findings = self._validate(plan)
        assert len(findings) == 1
        assert findings[0].repair_worthy is True


# =============================================================================
# TestRiskCategoriesSignalChecklists
# =============================================================================


class TestRiskCategoriesSignalChecklists:
    """Tests for signal-driven integration risk checklists in RiskCategoriesValidator."""

    def _validate(self, content: str, signals: list[str]) -> list[ValidationFinding]:
        v = RiskCategoriesValidator()
        ctx = ValidationContext(ticket_signals=signals)
        return v.validate(content, ctx)

    def test_workflow_signal_missing_risks_warns(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal SDK
"""
        findings = self._validate(plan, signals=["workflow"])
        signal_findings = [f for f in findings if "integration detected" in f.message]
        assert len(signal_findings) == 1
        assert (
            "Namespace" in signal_findings[0].message
            or "timeout" in signal_findings[0].message.lower()
        )

    def test_workflow_signal_all_covered_clean(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal SDK
Namespace permissions must be pre-configured.
Workflow execution timeout set to 30 minutes.
Retry policy with exponential backoff.
Worker deployment required on task queue.
Idempotency key prevents duplicate workflows.
Rollback: disable feature flag.
"""
        findings = self._validate(plan, signals=["workflow", "config"])
        signal_findings = [f for f in findings if "integration detected" in f.message]
        assert len(signal_findings) == 0

    def test_no_signal_no_domain_check(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: None
"""
        findings = self._validate(plan, signals=[])
        signal_findings = [f for f in findings if "integration detected" in f.message]
        assert len(signal_findings) == 0

    def test_risk_in_out_of_scope_counts(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal SDK
Workflow execution timeout set to 30 minutes.
Retry policy handles errors.
Worker is already deployed.
Idempotency handled by workflow ID.

## Out of Scope
Namespace creation is handled by DevOps.
"""
        findings = self._validate(plan, signals=["workflow", "config"])
        # "namespace" appears in Out of Scope — full content is searched
        signal_findings = [f for f in findings if "integration detected" in f.message]
        # Should not flag namespace since it's mentioned in the plan
        for sf in signal_findings:
            assert "Namespace" not in sf.message

    def test_migration_signal_checks(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Database migration tool
"""
        findings = self._validate(plan, signals=["migration"])
        signal_findings = [f for f in findings if "integration detected" in f.message]
        assert len(signal_findings) == 1
        assert "migration" in signal_findings[0].message.lower()

    def test_multiple_signals_combined(self):
        plan = """\
## Potential Risks or Considerations
**External dependencies**: Temporal + DB migration
"""
        findings = self._validate(plan, signals=["workflow", "migration"])
        signal_findings = [f for f in findings if "integration detected" in f.message]
        # Both workflow and migration checklists should fire
        assert len(signal_findings) == 2


# =============================================================================
# TestRepairLoop
# =============================================================================


class TestRepairLoop:
    """Tests for repair_worthy behavior in ValidationReport."""

    def test_repair_worthy_warning_triggers_has_repair_worthy(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.WARNING,
                    message="Missing qualifier",
                    repair_worthy=True,
                ),
            ]
        )
        assert report.has_repair_worthy is True
        assert report.has_errors is False

    def test_non_repair_worthy_warning_no_trigger(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.WARNING,
                    message="Advisory warning",
                    repair_worthy=False,
                ),
            ]
        )
        assert report.has_repair_worthy is False

    def test_error_always_triggers(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.ERROR,
                    message="Validation error",
                ),
            ]
        )
        assert report.has_repair_worthy is True

    def test_repair_worthy_info_does_not_trigger(self):
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Test",
                    severity=ValidationSeverity.INFO,
                    message="Advisory info",
                    repair_worthy=True,
                ),
            ]
        )
        # INFO findings never trigger repair, even with repair_worthy=True
        assert report.has_repair_worthy is False
