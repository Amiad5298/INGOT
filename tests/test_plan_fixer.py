"""Tests for ingot.validation.plan_fixer module."""

from pathlib import PurePosixPath
from unittest.mock import MagicMock

from ingot.validation.base import (
    ValidationContext,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)
from ingot.validation.plan_fixer import PlanFixer
from ingot.validation.plan_validators import FileExistsValidator


class TestPlanFixerBasic:
    """Core PlanFixer behavior."""

    def test_fix_missing_file_injects_unverified(self):
        """Single missing file -> UNVERIFIED marker injected."""
        content = "line1\nModify `src/missing.py` to add feature.\nline3"
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=2,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert len(fixes) == 1
        assert "src/missing.py" in fixes[0]
        assert "UNVERIFIED" in fixes[0]
        lines = fixed.split("\n")
        assert "<!-- UNVERIFIED: auto-flagged, file not in repo -->" in lines[1]

    def test_fix_multiple_missing_files(self):
        """Multiple errors -> all get markers."""
        content = "Modify `src/a.py` here.\nAlso `src/b.py` here.\nDone."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/a.py`",
                    line_number=1,
                ),
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/b.py`",
                    line_number=2,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert len(fixes) == 2
        lines = fixed.split("\n")
        assert "<!-- UNVERIFIED" in lines[0]
        assert "<!-- UNVERIFIED" in lines[1]
        assert "<!-- UNVERIFIED" not in lines[2]

    def test_fix_skips_already_marked_unverified(self):
        """Lines with existing UNVERIFIED -> no double-marking."""
        content = "Modify `src/a.py` here. <!-- UNVERIFIED: already marked -->"
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/a.py`",
                    line_number=1,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content  # Unchanged

    def test_fix_skips_already_marked_new_file(self):
        """Lines with existing NEW_FILE -> no double-marking."""
        content = "<!-- NEW_FILE --> `src/new.py` is the new service."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/new.py`",
                    line_number=1,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content

    def test_fix_only_targets_file_exists_errors(self):
        """RequiredSections errors -> untouched."""
        content = "# Plan\n\nMissing sections."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Required Sections",
                    severity=ValidationSeverity.ERROR,
                    message="Missing required section: 'Summary'",
                ),
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=3,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        # Only the File Exists error gets fixed
        assert len(fixes) == 1
        assert "src/missing.py" in fixes[0]

    def test_fix_idempotent(self):
        """Running fix twice -> same result."""
        content = "Modify `src/missing.py` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=1,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed_once, fixes_once = fixer.fix(content, report)
        fixed_twice, fixes_twice = fixer.fix(fixed_once, report)

        assert fixed_once == fixed_twice
        assert fixes_twice == []  # No new fixes on second pass

    def test_fix_returns_empty_when_no_errors(self):
        """Clean report -> no changes."""
        content = "# Plan\n\nEverything is fine."
        report = ValidationReport()

        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content

    def test_fix_returns_empty_when_only_warnings(self):
        """Warnings-only report -> no changes."""
        content = "# Plan\n\nSome content."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="Pattern Source",
                    severity=ValidationSeverity.WARNING,
                    message="Code block at line 5 has no citation.",
                    line_number=5,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content


class TestPlanFixerRevalidation:
    """Test that fixes survive revalidation."""

    def test_revalidation_passes_after_fix(self, tmp_path):
        """Fix + revalidate -> has_errors is False for File Exists."""
        plan = "Modify `src/nonexistent.py` to add the feature."

        # First validation: produces error
        validator = FileExistsValidator()
        ctx = ValidationContext(repo_root=tmp_path)
        findings = validator.validate(plan, ctx)
        report = ValidationReport(findings=findings)
        assert report.has_errors

        # Apply fix
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(plan, report)
        assert len(fixes) == 1

        # Revalidate: UNVERIFIED marker causes FileExistsValidator to skip the path
        findings2 = validator.validate(fixed, ctx)
        report2 = ValidationReport(findings=findings2)
        assert not report2.has_errors


class TestPlanFixerEdgeCases:
    """Edge cases for PlanFixer."""

    def test_fix_skips_finding_without_line_number(self):
        """Findings without line_number are skipped."""
        content = "Modify `src/missing.py` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=None,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content

    def test_fix_skips_out_of_range_line_number(self):
        """Line numbers beyond content range are skipped."""
        content = "Just one line."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=99,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content

    def test_fix_skips_non_matching_message_format(self):
        """Error messages that don't match expected format are skipped."""
        content = "Some content."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="Validator crashed: something",
                    line_number=1,
                ),
            ]
        )
        fixer = PlanFixer()
        fixed, fixes = fixer.fix(content, report)

        assert fixes == []
        assert fixed == content


class TestPlanFixerWithFileIndex:
    """Test PlanFixer with FileIndex integration."""

    def _make_mock_file_index(self, fuzzy_result=None):
        """Create a mock FileIndex with configurable fuzzy_find return."""
        mock = MagicMock()
        mock.fuzzy_find.return_value = fuzzy_result
        return mock

    def test_fuzzy_find_corrects_path(self):
        """FileIndex fuzzy match → path corrected inline."""
        content = "Modify `src/wrong/FooService.java` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/wrong/FooService.java`",
                    line_number=1,
                ),
            ]
        )
        mock_idx = self._make_mock_file_index(
            fuzzy_result=PurePosixPath("src/main/java/FooService.java")
        )
        fixer = PlanFixer(file_index=mock_idx)
        fixed, fixes = fixer.fix(content, report)

        assert len(fixes) == 1
        assert "Corrected" in fixes[0]
        assert "src/main/java/FooService.java" in fixed
        assert "src/wrong/FooService.java" not in fixed

    def test_fuzzy_find_no_match_falls_back_to_unverified(self):
        """No fuzzy match → fallback to UNVERIFIED stamping."""
        content = "Modify `src/missing.py` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=1,
                ),
            ]
        )
        mock_idx = self._make_mock_file_index(fuzzy_result=None)
        fixer = PlanFixer(file_index=mock_idx)
        fixed, fixes = fixer.fix(content, report)

        assert len(fixes) == 1
        assert "UNVERIFIED" in fixes[0]
        assert "<!-- UNVERIFIED" in fixed

    def test_no_file_index_behaves_like_before(self):
        """No FileIndex → same behavior as before (UNVERIFIED stamping)."""
        content = "Modify `src/missing.py` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/missing.py`",
                    line_number=1,
                ),
            ]
        )
        fixer = PlanFixer()  # No file_index
        fixed, fixes = fixer.fix(content, report)

        assert len(fixes) == 1
        assert "UNVERIFIED" in fixes[0]

    def test_fuzzy_find_called_with_filename_part(self):
        """FileIndex.fuzzy_find receives the filename, not the full path."""
        content = "Modify `src/deep/nested/MyFile.java` to add feature."
        report = ValidationReport(
            findings=[
                ValidationFinding(
                    validator_name="File Exists",
                    severity=ValidationSeverity.ERROR,
                    message="File not found: `src/deep/nested/MyFile.java`",
                    line_number=1,
                ),
            ]
        )
        mock_idx = self._make_mock_file_index(fuzzy_result=None)
        fixer = PlanFixer(file_index=mock_idx)
        fixer.fix(content, report)

        mock_idx.fuzzy_find.assert_called_once_with("MyFile.java")
