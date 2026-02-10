"""Tests for review status parser in ingot.workflow.review module.

Tests cover:
- Canonical Status: format (bold and non-bold)
- Bullet format (- **PASS** - description)
- Standalone markers near the end
- Multiple status markers (last one wins)
- False positive prevention (PASS in normal prose)
"""

from ingot.workflow.review import ReviewStatus, parse_review_status


class TestParseReviewStatusCanonical:
    def test_parse_pass_with_bold_markers(self):
        output = """## Task Review: Example Task

**Status**: PASS

**Summary**: Everything looks good!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_parse_pass_without_bold_markers(self):
        output = """## Task Review: Example Task

Status: PASS

Summary: Everything looks good!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_parse_needs_attention_with_bold_markers(self):
        output = """## Task Review: Example Task

**Status**: NEEDS_ATTENTION

**Issues**:
- Missing error handling
- Incomplete tests
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_parse_needs_attention_without_bold_markers(self):
        output = """## Task Review: Example Task

Status: NEEDS_ATTENTION

Issues:
- Missing error handling
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_case_insensitive_matching(self):
        assert parse_review_status("**Status**: pass\n\nLooks good!") == ReviewStatus.PASS
        assert parse_review_status("**Status**: Pass\n") == ReviewStatus.PASS
        assert parse_review_status("Status: needs_attention\n") == ReviewStatus.NEEDS_ATTENTION

    def test_whitespace_variations(self):
        assert parse_review_status("**Status**:    PASS   \n") == ReviewStatus.PASS
        assert parse_review_status("Status :PASS\n") == ReviewStatus.PASS
        assert parse_review_status("**Status** : NEEDS_ATTENTION") == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusBulletFormat:
    def test_bullet_pass_with_description(self):
        output = """## Review Complete

- **PASS** - Changes look good, ready to proceed
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_bullet_needs_attention_with_description(self):
        output = """## Review Complete

- **NEEDS_ATTENTION** - Issues found that should be addressed

**Issues**:
1. Missing test coverage
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_bullet_without_trailing_dash(self):
        output = """## Review

- **PASS**
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_bullet_needs_attention_without_trailing_dash(self):
        output = """## Review

- **NEEDS_ATTENTION**
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusStandalone:
    def test_standalone_bold_pass_at_end(self):
        output = """## Task Review

Everything looks good.

**PASS**
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_standalone_pass_at_end(self):
        output = """## Task Review

Everything looks good.

PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_standalone_needs_attention_at_end(self):
        output = """## Task Review

Found some issues.

NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_standalone_bold_needs_attention_at_end(self):
        output = """## Task Review

Found issues.

**NEEDS_ATTENTION**
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusMultipleMarkers:
    def test_uses_last_status_marker(self):
        output = """## Initial Review

**Status**: NEEDS_ATTENTION

Issues found.

## After Fix

**Status**: PASS

All issues resolved!
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_both_markers_present_uses_last(self):
        output = """**Status**: PASS

Wait, actually found an issue.

**Status**: NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_mixed_bold_and_plain_markers(self):
        output = """Status: NEEDS_ATTENTION

After review:

**Status**: PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS

    def test_canonical_overrides_bullet_if_later(self):
        output = """- **NEEDS_ATTENTION** - Initial review

After fixes:

**Status**: PASS
"""
        assert parse_review_status(output) == ReviewStatus.PASS


class TestParseReviewStatusFalsePositives:
    def test_ignores_pass_in_normal_text(self):
        output = """## Task Review: Example Task

The implementation will PASS all tests once complete.

**Status**: NEEDS_ATTENTION

**Issues**:
- Tests not yet written
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_ignores_pass_in_sentence(self):
        output = """This will PASS the validation checks.

**Status**: NEEDS_ATTENTION
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_ignores_pass_without_status_marker(self):
        output = """## Review

The tests will PASS once you add the missing import.
Please fix the import and try again.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_pass_in_code_block_ignored(self):
        output = """## Review

```python
assert result == "PASS"
```

No status marker here.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION


class TestParseReviewStatusEdgeCases:
    def test_empty_output_returns_needs_attention(self):
        assert parse_review_status("") == ReviewStatus.NEEDS_ATTENTION
        assert parse_review_status("   ") == ReviewStatus.NEEDS_ATTENTION
        assert parse_review_status("\n\n") == ReviewStatus.NEEDS_ATTENTION

    def test_no_status_marker_returns_needs_attention(self):
        output = """## Task Review

Some review text without a clear status marker.
"""
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_none_input_handled(self):
        assert parse_review_status("") == ReviewStatus.NEEDS_ATTENTION

    def test_very_long_output_uses_last_500_chars_for_fallback(self):
        # Create long output with PASS early (should be ignored) and nothing at end
        preamble = "x" * 1000
        output = f"{preamble}\n\nPASS\n\n{'y' * 600}"
        # PASS is in the middle, not in last 500 chars, so should be NEEDS_ATTENTION
        assert parse_review_status(output) == ReviewStatus.NEEDS_ATTENTION

    def test_long_output_with_pass_at_end(self):
        preamble = "x" * 1000
        output = f"{preamble}\n\n**Status**: PASS\n"
        assert parse_review_status(output) == ReviewStatus.PASS


class TestBuildReviewPrompt:
    def test_builds_prompt_with_phase_and_diff(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "specs/TEST-123-plan.md"
        state.user_context = ""

        result = build_review_prompt(
            state=state,
            phase="fundamental",
            diff_output="diff --git a/file.py b/file.py\n+new line",
            is_truncated=False,
        )

        assert "fundamental" in result
        assert "specs/TEST-123-plan.md" in result
        assert "diff --git a/file.py b/file.py" in result
        assert "**Status**: PASS" in result
        assert "Large Changeset" not in result

    def test_includes_large_changeset_instructions_when_truncated(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "specs/PROJ-456-plan.md"
        state.user_context = ""

        result = build_review_prompt(
            state=state,
            phase="final",
            diff_output="file1.py | 10 ++++\nfile2.py | 5 ++",
            is_truncated=True,
        )

        assert "final" in result
        assert "Large Changeset" in result
        assert "git diff -- <file_path>" in result

    def test_includes_review_instructions(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "plan.md"
        state.user_context = ""

        result = build_review_prompt(
            state=state,
            phase="fundamental",
            diff_output="some diff",
            is_truncated=False,
        )

        assert "Review Instructions" in result
        assert "align with the implementation plan" in result
        assert "NEEDS_ATTENTION" in result

    def test_includes_user_context_when_provided(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "plan.md"
        state.user_context = "Focus on backward compatibility"

        result = build_review_prompt(
            state=state,
            phase="fundamental",
            diff_output="some diff",
            is_truncated=False,
        )

        assert "Additional Context" in result
        assert "Focus on backward compatibility" in result

    def test_excludes_user_context_when_empty(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "plan.md"
        state.user_context = ""

        result = build_review_prompt(
            state=state,
            phase="fundamental",
            diff_output="some diff",
            is_truncated=False,
        )

        assert "Additional Context" not in result

    def test_excludes_user_context_when_whitespace_only(self):
        from unittest.mock import MagicMock

        from ingot.workflow.review import build_review_prompt

        state = MagicMock()
        state.get_plan_path.return_value = "plan.md"
        state.user_context = "   \n  "

        result = build_review_prompt(
            state=state,
            phase="fundamental",
            diff_output="some diff",
            is_truncated=False,
        )

        assert "Additional Context" not in result


class TestGetDiffForReview:
    def test_uses_baseline_when_available(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _get_diff_for_review

        state = MagicMock()
        state.diff_baseline_ref = "abc123"

        with patch("ingot.workflow.review.get_smart_diff_from_baseline") as mock_baseline:
            mock_baseline.return_value = ("diff output", False, False)
            result = _get_diff_for_review(state)

            mock_baseline.assert_called_once_with("abc123", include_working_tree=True)
            assert result == ("diff output", False, False)

    def test_falls_back_to_smart_diff_when_no_baseline(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _get_diff_for_review

        state = MagicMock()
        state.diff_baseline_ref = None

        with patch("ingot.workflow.review.get_smart_diff") as mock_smart:
            mock_smart.return_value = ("legacy diff", True, False)
            result = _get_diff_for_review(state)

            mock_smart.assert_called_once()
            assert result == ("legacy diff", True, False)


class TestRunPhaseReview:
    def test_returns_true_when_no_changes(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("", False, False)  # Empty diff
            with patch("ingot.workflow.review.print_info"):
                result = run_phase_review(state, MagicMock(), "fundamental", backend=MagicMock())

        assert result is True

    def test_returns_true_when_review_passes(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}

        mock_backend = MagicMock()
        mock_backend.run_with_callback.return_value = (True, "**Status**: PASS")

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("diff content", False, False)
            with patch("ingot.workflow.review.print_step"):
                with patch("ingot.workflow.review.print_success"):
                    result = run_phase_review(
                        state, MagicMock(), "fundamental", backend=mock_backend
                    )

        assert result is True

    def test_prompts_for_git_error(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("", False, True)  # git_error=True
            with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
                mock_confirm.return_value = True  # User continues
                with patch("ingot.workflow.review.print_warning"):
                    with patch("ingot.workflow.review.print_info"):
                        with patch("ingot.workflow.review.print_step"):
                            result = run_phase_review(
                                state, MagicMock(), "final", backend=MagicMock()
                            )

        assert result is True
        mock_confirm.assert_called_once()

    def test_returns_false_when_user_stops_after_git_error(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("", False, True)  # git_error=True
            with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
                mock_confirm.return_value = False  # User stops
                with patch("ingot.workflow.review.print_warning"):
                    with patch("ingot.workflow.review.print_info"):
                        with patch("ingot.workflow.review.print_step"):
                            result = run_phase_review(
                                state, MagicMock(), "final", backend=MagicMock()
                            )

        assert result is False

    def test_offers_autofix_on_needs_attention(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}

        mock_backend = MagicMock()
        mock_backend.run_with_callback.return_value = (
            True,
            "**Status**: NEEDS_ATTENTION\n**Issues**: 1. Bug",
        )

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("diff content", False, False)
            with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
                # First confirm = auto-fix (No), second = continue (Yes)
                mock_confirm.side_effect = [False, True]
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        result = run_phase_review(
                            state, MagicMock(), "fundamental", backend=mock_backend
                        )

        assert result is True
        # Should be called twice: auto-fix prompt and continue prompt
        assert mock_confirm.call_count == 2

    def test_runs_autofix_when_user_accepts(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}

        mock_backend = MagicMock()
        mock_backend.run_with_callback.return_value = (
            True,
            "**Status**: NEEDS_ATTENTION",
        )

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("diff content", False, False)
            with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
                # auto-fix (Yes), re-review (No), continue (Yes)
                mock_confirm.side_effect = [True, False, True]
                # Patch autofix in its source module since it's imported inside the function
                with patch("ingot.workflow.autofix.run_auto_fix") as mock_autofix:
                    mock_autofix.return_value = True
                    with patch("ingot.workflow.review.print_step"):
                        with patch("ingot.workflow.review.print_warning"):
                            result = run_phase_review(
                                state, MagicMock(), "fundamental", backend=mock_backend
                            )

        mock_autofix.assert_called_once()
        assert result is True

    def test_handles_review_execution_exception(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}

        mock_backend = MagicMock()
        mock_backend.run_with_callback.side_effect = Exception("Network error")

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("diff content", False, False)
            with patch("ingot.workflow.review.print_step"):
                with patch("ingot.workflow.review.print_warning"):
                    with patch("ingot.workflow.review.print_info"):
                        result = run_phase_review(
                            state, MagicMock(), "fundamental", backend=mock_backend
                        )

        # Should continue workflow on review crash (advisory behavior)
        assert result is True

    def test_prompts_user_on_execution_failure(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import run_phase_review

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}

        mock_backend = MagicMock()
        mock_backend.run_with_callback.return_value = (False, "Error output")

        with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
            mock_diff.return_value = ("diff content", False, False)
            with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
                mock_confirm.return_value = True
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        with patch("ingot.workflow.review.print_info"):
                            result = run_phase_review(
                                state, MagicMock(), "final", backend=mock_backend
                            )

        assert result is True
        mock_confirm.assert_called_once()


class TestRunRereviewAfterFix:
    def test_returns_none_when_user_skips(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        auggie_client = MagicMock()

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = False
            result = _run_rereview_after_fix(state, MagicMock(), "fundamental", auggie_client)

        assert result is None

    def test_returns_true_when_no_changes_after_fix(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        auggie_client = MagicMock()

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("", False, False)  # No changes
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_info"):
                        result = _run_rereview_after_fix(
                            state, MagicMock(), "fundamental", auggie_client
                        )

        assert result is True

    def test_returns_true_when_rereview_passes(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}
        auggie_client = MagicMock()
        auggie_client.run_with_callback.return_value = (True, "**Status**: PASS")

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("diff content", False, False)
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_success"):
                        result = _run_rereview_after_fix(
                            state, MagicMock(), "fundamental", auggie_client
                        )

        assert result is True

    def test_returns_none_when_rereview_fails(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}
        auggie_client = MagicMock()
        auggie_client.run_with_callback.return_value = (True, "**Status**: NEEDS_ATTENTION")

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("diff content", False, False)
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        with patch("ingot.workflow.review.print_info"):
                            result = _run_rereview_after_fix(
                                state, MagicMock(), "fundamental", auggie_client
                            )

        assert result is None

    def test_returns_none_on_git_error(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        auggie_client = MagicMock()

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("", False, True)  # git_error=True
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        result = _run_rereview_after_fix(
                            state, MagicMock(), "fundamental", auggie_client
                        )

        assert result is None

    def test_returns_none_on_execution_failure(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}
        auggie_client = MagicMock()
        auggie_client.run_with_callback.return_value = (False, "error")

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("diff content", False, False)
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        result = _run_rereview_after_fix(
                            state, MagicMock(), "fundamental", auggie_client
                        )

        assert result is None

    def test_returns_none_on_exception(self):
        from unittest.mock import MagicMock, patch

        from ingot.workflow.review import _run_rereview_after_fix

        state = MagicMock()
        state.diff_baseline_ref = None
        state.subagent_names = {"reviewer": "ingot-reviewer"}
        auggie_client = MagicMock()
        auggie_client.run_with_callback.side_effect = Exception("Network error")

        with patch("ingot.workflow.review.prompt_confirm") as mock_confirm:
            mock_confirm.return_value = True
            with patch("ingot.workflow.review.get_smart_diff") as mock_diff:
                mock_diff.return_value = ("diff content", False, False)
                with patch("ingot.workflow.review.print_step"):
                    with patch("ingot.workflow.review.print_warning"):
                        result = _run_rereview_after_fix(
                            state, MagicMock(), "fundamental", auggie_client
                        )

        assert result is None
