"""Tests for review status parser in spec.workflow.review module.

Tests cover:
- Canonical Status: format (bold and non-bold)
- Bullet format (- **PASS** - description)
- Standalone markers near the end
- Multiple status markers (last one wins)
- False positive prevention (PASS in normal prose)
"""

import pytest

from specflow.workflow.review import parse_review_status, ReviewStatus


class TestParseReviewStatusCanonical:
    """Tests for canonical **Status**: PASS/NEEDS_ATTENTION format."""

    def test_parse_pass_with_bold_markers(self):
        """Parses PASS with bold markers."""
        output = """## Task Review: Example Task

**Status**: PASS

**Summary**: Everything looks good!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_parse_pass_without_bold_markers(self):
        """Parses PASS without bold markers."""
        output = """## Task Review: Example Task

Status: PASS

Summary: Everything looks good!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_parse_needs_attention_with_bold_markers(self):
        """Parses NEEDS_ATTENTION with bold markers."""
        output = """## Task Review: Example Task

**Status**: NEEDS_ATTENTION

**Issues**:
- Missing error handling
- Incomplete tests
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_parse_needs_attention_without_bold_markers(self):
        """Parses NEEDS_ATTENTION without bold markers."""
        output = """## Task Review: Example Task

Status: NEEDS_ATTENTION

Issues:
- Missing error handling
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_case_insensitive_matching(self):
        """Handles case variations."""
        assert parse_review_status("**Status**: pass\n\nLooks good!") == ReviewStatus.PASS
        assert parse_review_status("**Status**: Pass\n") == ReviewStatus.PASS
        assert parse_review_status("Status: needs_attention\n") == ReviewStatus.NEEDS_ATTENTION

    def test_whitespace_variations(self):
        """Handles whitespace variations around colon."""
        assert parse_review_status("**Status**:    PASS   \n") == ReviewStatus.PASS
        assert parse_review_status("Status :PASS\n") == ReviewStatus.PASS
        assert parse_review_status("**Status** : NEEDS_ATTENTION") == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusBulletFormat:
    """Tests for bullet format: - **PASS** - description."""

    def test_bullet_pass_with_description(self):
        """Parses bullet format - **PASS** - description."""
        output = """## Review Complete

- **PASS** - Changes look good, ready to proceed
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_bullet_needs_attention_with_description(self):
        """Parses bullet format - **NEEDS_ATTENTION** - description."""
        output = """## Review Complete

- **NEEDS_ATTENTION** - Issues found that should be addressed

**Issues**:
1. Missing test coverage
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_bullet_without_trailing_dash(self):
        """Parses bullet format without trailing dash."""
        output = """## Review

- **PASS**
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_bullet_needs_attention_without_trailing_dash(self):
        """Parses bullet NEEDS_ATTENTION without trailing dash."""
        output = """## Review

- **NEEDS_ATTENTION**
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusStandalone:
    """Tests for standalone markers near the end."""

    def test_standalone_bold_pass_at_end(self):
        """Detects standalone **PASS** marker at end."""
        output = """## Task Review

Everything looks good.

**PASS**
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_standalone_pass_at_end(self):
        """Detects standalone PASS on its own line at end."""
        output = """## Task Review

Everything looks good.

PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_standalone_needs_attention_at_end(self):
        """Detects standalone NEEDS_ATTENTION marker at end."""
        output = """## Task Review

Found some issues.

NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_standalone_bold_needs_attention_at_end(self):
        """Detects standalone **NEEDS_ATTENTION** at end."""
        output = """## Task Review

Found issues.

**NEEDS_ATTENTION**
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusMultipleMarkers:
    """Tests for multiple status markers (last one wins)."""

    def test_uses_last_status_marker(self):
        """Uses the last status marker as final verdict."""
        output = """## Initial Review

**Status**: NEEDS_ATTENTION

Issues found.

## After Fix

**Status**: PASS

All issues resolved!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_both_markers_present_uses_last(self):
        """When both markers present, uses the last one."""
        output = """**Status**: PASS

Wait, actually found an issue.

**Status**: NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_mixed_bold_and_plain_markers(self):
        """Handles mixed bold and plain markers."""
        output = """Status: NEEDS_ATTENTION

After review:

**Status**: PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_canonical_overrides_bullet_if_later(self):
        """Canonical format overrides bullet if it appears later."""
        output = """- **NEEDS_ATTENTION** - Initial review

After fixes:

**Status**: PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS


class TestParseReviewStatusFalsePositives:
    """Tests that PASS in normal prose does NOT trigger false positives."""

    def test_ignores_pass_in_normal_text(self):
        """Ignores PASS appearing in normal text."""
        output = """## Task Review: Example Task

The implementation will PASS all tests once complete.

**Status**: NEEDS_ATTENTION

**Issues**:
- Tests not yet written
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_ignores_pass_in_sentence(self):
        """Ignores PASS in middle of sentence."""
        output = """This will PASS the validation checks.

**Status**: NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_ignores_pass_without_status_marker(self):
        """PASS in prose without Status marker returns NEEDS_ATTENTION."""
        output = """## Review

The tests will PASS once you add the missing import.
Please fix the import and try again.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_pass_in_code_block_ignored(self):
        """PASS in code context is ignored without explicit marker."""
        output = """## Review

```python
assert result == "PASS"
```

No status marker here.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusEdgeCases:
    """Tests for edge cases and fail-safe behavior."""

    def test_empty_output_returns_needs_attention(self):
        """Empty output returns NEEDS_ATTENTION (fail-safe)."""
        assert parse_review_status("") == ReviewStatus.NEEDS_ATTENTION
        assert parse_review_status("   ") == ReviewStatus.NEEDS_ATTENTION
        assert parse_review_status("\n\n") == ReviewStatus.NEEDS_ATTENTION

    def test_no_status_marker_returns_needs_attention(self):
        """No status marker returns NEEDS_ATTENTION (fail-safe)."""
        output = """## Task Review

Some review text without a clear status marker.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_none_input_handled(self):
        """None-like empty string handled gracefully."""
        assert parse_review_status("") == ReviewStatus.NEEDS_ATTENTION

    def test_very_long_output_uses_last_500_chars_for_fallback(self):
        """Long output uses last 500 chars for standalone marker fallback."""
        # Create long output with PASS early (should be ignored) and nothing at end
        preamble = "x" * 1000
        output = f"{preamble}\n\nPASS\n\n{'y' * 600}"
        # PASS is in the middle, not in last 500 chars, so should be NEEDS_ATTENTION
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_long_output_with_pass_at_end(self):
        """Long output with PASS in last 500 chars is detected."""
        preamble = "x" * 1000
        output = f"{preamble}\n\n**Status**: PASS\n"
        assert parse_review_status(output) == ReviewStatus.PASS


# Backwards compatibility test - ensure the re-exported alias works
class TestBackwardsCompatibility:
    """Tests for backwards compatibility with underscore-prefixed alias."""

    def test_underscore_alias_works(self):
        """The _parse_review_status alias works for backwards compat."""
        from specflow.workflow.step3_execute import _parse_review_status
        assert _parse_review_status("**Status**: PASS\n") == ReviewStatus.PASS
        assert _parse_review_status("Status: NEEDS_ATTENTION") == ReviewStatus.NEEDS_ATTENTION

