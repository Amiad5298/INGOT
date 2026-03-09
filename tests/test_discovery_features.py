"""Tests for Phase 3 performance features: caching, timeouts, scoping, signals."""

from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock, patch

from ingot.discovery.context_builder import ContextBuilder
from ingot.discovery.grep_engine import GrepEngine
from ingot.validation.base import ValidationContext, ValidationSeverity
from ingot.validation.plan_validators import (
    OperationalCompletenessValidator,
    SnippetCompletenessValidator,
)
from ingot.workflow.step1_plan import _extract_ticket_signals, _extract_ticket_structured_fields

# =============================================================================
# Ticket Signal Extraction
# =============================================================================


class TestTicketSignalExtraction:
    """Tests for _extract_ticket_signals()."""

    def test_metric_signal(self):
        signals = _extract_ticket_signals("Add Prometheus metrics for queue depth")
        assert "metric" in signals

    def test_alert_signal(self):
        signals = _extract_ticket_signals("Configure PagerDuty alerting for high latency")
        assert "alert" in signals

    def test_monitor_signal(self):
        signals = _extract_ticket_signals("Add health check monitoring dashboard")
        assert "monitor" in signals

    def test_endpoint_signal(self):
        signals = _extract_ticket_signals("Create REST API endpoint for user profiles")
        assert "endpoint" in signals

    def test_migration_signal(self):
        signals = _extract_ticket_signals("Database schema migration for user table")
        assert "migration" in signals

    def test_config_signal(self):
        signals = _extract_ticket_signals("Update feature flag configuration for dark mode")
        assert "config" in signals

    def test_refactor_signal(self):
        signals = _extract_ticket_signals("Refactor authentication module")
        assert "refactor" in signals

    def test_security_signal(self):
        signals = _extract_ticket_signals("Add OAuth2 authentication flow")
        assert "security" in signals

    def test_test_signal(self):
        signals = _extract_ticket_signals("Add integration test coverage for payments")
        assert "test" in signals

    def test_multiple_signals(self):
        signals = _extract_ticket_signals(
            "Add Prometheus metric and PagerDuty alert for SQS queue monitoring"
        )
        assert "metric" in signals
        assert "alert" in signals
        assert "monitor" in signals

    def test_empty_text(self):
        signals = _extract_ticket_signals("")
        assert signals == []

    def test_no_matching_signals(self):
        signals = _extract_ticket_signals("Fix typo in README")
        assert signals == []

    def test_case_insensitive(self):
        signals = _extract_ticket_signals("PROMETHEUS METRICS for monitoring")
        assert "metric" in signals

    def test_workflow_signal(self):
        signals = _extract_ticket_signals("Integrate Temporal workflow for grace period")
        assert "workflow" in signals

    def test_workflow_signal_state_machine(self):
        signals = _extract_ticket_signals("Implement state machine action for order processing")
        assert "workflow" in signals

    def test_workflow_signal_saga(self):
        signals = _extract_ticket_signals("Implement saga pattern for distributed transactions")
        assert "workflow" in signals


# =============================================================================
# Ticket Structured Field Extraction
# =============================================================================


class TestExtractTicketStructuredFields:
    """Tests for _extract_ticket_structured_fields()."""

    def test_empty_text(self):
        fields = _extract_ticket_structured_fields("")
        assert fields == {
            "files_to_modify": [],
            "acceptance_criteria": [],
            "feature_flags": [],
            "dependencies": [],
        }

    def test_files_to_modify_h3(self):
        text = """### Files to Modify
- GracePeriodStartAction.java — Enhance to start Temporal workflow
- MarketplaceConfig.java — Add WorkflowClient bean
- TemporalConfig.java — NEW
"""
        fields = _extract_ticket_structured_fields(text)
        assert len(fields["files_to_modify"]) == 3
        assert "GracePeriodStartAction.java" in fields["files_to_modify"][0]
        assert "TemporalConfig.java" in fields["files_to_modify"][2]

    def test_acceptance_criteria_bold(self):
        text = """**Acceptance Criteria**
- GracePeriodStartAction starts Temporal workflow after sending notification
- Temporal client is configured with proper connection settings
- Unit tests verify Temporal client is called correctly
"""
        fields = _extract_ticket_structured_fields(text)
        assert len(fields["acceptance_criteria"]) == 3
        assert "Temporal workflow" in fields["acceptance_criteria"][0]

    def test_feature_flags(self):
        text = """## Feature Flags
- enable.grace.period.temporal — Controls Temporal workflow activation
"""
        fields = _extract_ticket_structured_fields(text)
        assert len(fields["feature_flags"]) == 1

    def test_mixed_sections(self):
        text = """## Files to Modify
- Action.java — modify
- Config.java — add bean

## Acceptance Criteria
- Feature works correctly
- Tests pass

## Feature Flag
- my.feature.flag — toggle
"""
        fields = _extract_ticket_structured_fields(text)
        assert len(fields["files_to_modify"]) == 2
        assert len(fields["acceptance_criteria"]) == 2
        assert len(fields["feature_flags"]) == 1

    def test_no_matching_sections(self):
        text = """## Summary
This ticket implements a new feature.

## Description
Detailed description of the feature.
"""
        fields = _extract_ticket_structured_fields(text)
        assert all(v == [] for v in fields.values())

    def test_numbered_bullets(self):
        text = """### Acceptance Criteria
1. First criterion
2. Second criterion
3. Third criterion
"""
        fields = _extract_ticket_structured_fields(text)
        assert len(fields["acceptance_criteria"]) == 3


# =============================================================================
# GrepEngine Caching
# =============================================================================


class TestGrepEngineCaching:
    """Tests for GrepEngine result caching."""

    def test_search_caches_results(self, tmp_path):
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("test.py")],
        )

        # First search
        results1 = engine.search("hello")
        assert len(results1) == 1

        # Delete the file — cached result should still be returned
        test_file.unlink()
        results2 = engine.search("hello")
        assert len(results2) == 1
        assert results1[0].line_content == results2[0].line_content

    def test_different_patterns_not_cached(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("test.py")],
        )

        results_hello = engine.search("hello")
        results_world = engine.search("world")
        assert len(results_hello) == 1
        assert len(results_world) == 1
        assert results_hello[0].line_content != results_world[0].line_content

    def test_case_sensitivity_creates_separate_cache_entry(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def Hello():\n    pass\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("test.py")],
        )

        results_sensitive = engine.search("hello", ignore_case=False)
        results_insensitive = engine.search("hello", ignore_case=True)
        assert len(results_sensitive) == 0
        assert len(results_insensitive) == 1


# =============================================================================
# GrepEngine Timeout
# =============================================================================


class TestGrepEngineTimeout:
    """Tests for GrepEngine search timeout."""

    def test_timeout_stops_search(self, tmp_path):
        # Create many files to ensure timeout is hit
        for i in range(100):
            (tmp_path / f"file_{i}.py").write_text(f"line {i}\n" * 100)

        file_paths = [PurePosixPath(f"file_{i}.py") for i in range(100)]

        engine = GrepEngine(
            tmp_path,
            file_paths,
            search_timeout=10.0,
        )

        # Mock time.monotonic so the deadline expires immediately
        call_count = 0

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            # First call sets the deadline; subsequent calls exceed it
            return 0.0 if call_count <= 1 else 100.0

        with patch("ingot.discovery.grep_engine.time.monotonic", side_effect=fake_monotonic):
            result = engine.search_with_meta("line")

        assert result.meta.was_truncated
        assert result.meta.truncation_reason == "timeout"

    def test_normal_timeout_completes(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("test.py")],
            search_timeout=30.0,
        )

        results = engine.search("hello")
        assert len(results) == 1


# =============================================================================
# ContextBuilder Large Repo Scoping
# =============================================================================


class TestContextBuilderLargeRepoScoping:
    """Tests for ContextBuilder._scope_paths_for_large_repo()."""

    def test_scoping_reduces_paths(self):
        # Mock FileIndex with many paths
        mock_index = MagicMock()
        all_paths = [
            PurePosixPath(f"src/module{i}/file{j}.py") for i in range(100) for j in range(10)
        ]
        mock_index.all_paths.return_value = all_paths
        mock_index.file_count = len(all_paths)

        # Keyword matches only in module5
        mock_index.find_by_stem.side_effect = lambda stem: (
            [PurePosixPath("src/module5/service.py")] if stem == "service" else []
        )

        scoped = ContextBuilder._scope_paths_for_large_repo(mock_index, ["service"])

        # Should include files from module5 and its parent (src)
        assert len(scoped) < len(all_paths)
        # Files from module5 should be included
        assert any("module5" in str(p) for p in scoped)

    def test_scoping_falls_back_when_no_stems_match(self):
        mock_index = MagicMock()
        all_paths = [PurePosixPath(f"file{i}.py") for i in range(10)]
        mock_index.all_paths.return_value = all_paths
        mock_index.find_by_stem.return_value = []

        scoped = ContextBuilder._scope_paths_for_large_repo(mock_index, ["nonexistent"])

        assert scoped == all_paths  # Falls back to all paths


# =============================================================================
# Signal-Based Validator Severity Elevation
# =============================================================================


class TestSignalBasedSeverity:
    """Tests for OperationalCompletenessValidator severity elevation via signals."""

    def test_info_severity_without_signals(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nAdd Prometheus gauge metric for queue monitoring.\n"
        ctx = ValidationContext(ticket_signals=[])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO

    def test_warning_severity_with_metric_signal(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nAdd Prometheus gauge metric for queue monitoring.\n"
        ctx = ValidationContext(ticket_signals=["metric"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING

    def test_warning_severity_with_alert_signal(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nAdd alert rules for queue depth monitoring.\n"
        ctx = ValidationContext(ticket_signals=["alert"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING

    def test_warning_severity_with_monitor_signal(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nAdd dashboard for monitoring queue depth.\n"
        ctx = ValidationContext(ticket_signals=["monitor"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.WARNING

    def test_unrelated_signal_stays_info(self):
        v = OperationalCompletenessValidator()
        plan = "## Summary\nAdd Prometheus gauge metric for queue monitoring.\n"
        ctx = ValidationContext(ticket_signals=["refactor", "config"])
        findings = v.validate(plan, ctx)
        assert len(findings) == 1
        assert findings[0].severity == ValidationSeverity.INFO


# =============================================================================
# B1 — Java field regex handles generics, arrays, annotations
# =============================================================================


class TestSnippetCompletenessJavaRegex:
    """B1: SnippetCompletenessValidator detects generic/annotation Java fields."""

    def _make_plan(self, field_line: str) -> str:
        return f"## Code\n```java\n{field_line}\n```\n"

    def test_generic_field(self):
        v = SnippetCompletenessValidator()
        plan = self._make_plan("private final List<String> names;")
        findings = v.validate(plan, ValidationContext())
        assert any("fields" in f.message for f in findings)

    def test_array_field(self):
        v = SnippetCompletenessValidator()
        plan = self._make_plan("private byte[] data;")
        findings = v.validate(plan, ValidationContext())
        assert any("fields" in f.message for f in findings)

    def test_annotated_field(self):
        v = SnippetCompletenessValidator()
        plan = self._make_plan("@Nullable private String name;")
        findings = v.validate(plan, ValidationContext())
        assert any("fields" in f.message for f in findings)

    def test_annotated_with_args(self):
        v = SnippetCompletenessValidator()
        # Use @Column (not @Inject/@Autowired which trigger the init-pattern detector)
        plan = self._make_plan('@Column("name") private String userName;')
        findings = v.validate(plan, ValidationContext())
        assert any("fields" in f.message for f in findings)

    def test_protected_field(self):
        v = SnippetCompletenessValidator()
        plan = self._make_plan("protected final Map<String, Integer> lookup;")
        findings = v.validate(plan, ValidationContext())
        assert any("fields" in f.message for f in findings)


# =============================================================================
# B2 — Cached SearchResult preserves meta
# =============================================================================


class TestGrepEngineCacheMetaPreservation:
    """B2: Cached SearchResult retains original metadata (was_truncated, etc.)."""

    def test_cached_meta_preserved(self, tmp_path):
        test_file = tmp_path / "a.py"
        test_file.write_text("hello\n")

        engine = GrepEngine(tmp_path, [PurePosixPath("a.py")])

        first = engine.search_with_meta("hello")
        assert first.meta.files_searched == 1
        assert not first.meta.was_truncated

        # Second call hits cache — meta should be identical
        second = engine.search_with_meta("hello")
        assert second.meta.files_searched == first.meta.files_searched
        assert second.meta.was_truncated == first.meta.was_truncated
        assert second.meta.files_total == first.meta.files_total

    def test_cache_returns_same_result_object(self, tmp_path):
        test_file = tmp_path / "a.py"
        test_file.write_text("hello\n")

        engine = GrepEngine(tmp_path, [PurePosixPath("a.py")])
        first = engine.search_with_meta("hello")
        second = engine.search_with_meta("hello")
        # Should be the exact same SearchResult object
        assert first is second


# =============================================================================
# R10 — Truncated batch must not pollute single-pattern cache
# =============================================================================


class TestTruncatedBatchNotCachedForSingleSearch:
    """R10: Truncated batch results are not cached for single-pattern search."""

    def test_truncated_batch_not_cached(self, tmp_path):
        # Create enough matches to hit the total limit
        for i in range(60):
            (tmp_path / f"f{i}.py").write_text("match\n" * 20)

        paths = [PurePosixPath(f"f{i}.py") for i in range(60)]
        engine = GrepEngine(tmp_path, paths, max_matches_total=10)

        batch = engine.search_batch_with_meta(["match", "nomatch"])
        assert batch["match"].meta.was_truncated

        # Single-pattern search should NOT hit cache (truncated batch)
        single = engine.search_with_meta("match")
        # A cache hit would return the exact same object; a fresh search
        # produces a new SearchResult, proving the truncated batch was
        # not cached for single-pattern lookups.
        assert single is not batch["match"]

    def test_non_truncated_batch_is_cached(self, tmp_path):
        test_file = tmp_path / "a.py"
        test_file.write_text("hello\nworld\n")

        engine = GrepEngine(tmp_path, [PurePosixPath("a.py")])
        batch = engine.search_batch_with_meta(["hello"])
        assert not batch["hello"].meta.was_truncated

        # Single-pattern search should now hit cache
        single = engine.search_with_meta("hello")
        assert single is batch["hello"]


# =============================================================================
# R4 — Batch truncation marks all patterns
# =============================================================================


class TestGrepEngineBatchTruncation:
    """R4: When a batch is truncated, all pattern results share was_truncated."""

    def test_both_patterns_marked_truncated(self, tmp_path):
        for i in range(20):
            (tmp_path / f"f{i}.py").write_text("alpha\nbeta\n" * 10)

        paths = [PurePosixPath(f"f{i}.py") for i in range(20)]
        engine = GrepEngine(tmp_path, paths, max_matches_total=5)

        batch = engine.search_batch_with_meta(["alpha", "beta"])
        # At least one pattern should have was_truncated
        assert any(sr.meta.was_truncated for sr in batch.values())
        # The shared truncation flag means ALL patterns get was_truncated
        for sr in batch.values():
            assert sr.meta.was_truncated


# =============================================================================
# R3 — Line length cap
# =============================================================================


class TestGrepEngineLineCap:
    """R3: Lines exceeding max_line_length are truncated."""

    def test_long_line_truncated(self, tmp_path):
        long_line = "x" * 20_000
        (tmp_path / "big.py").write_text(long_line + "\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("big.py")],
            max_line_length=100,
        )
        results = engine.search("x+")
        assert len(results) == 1
        assert len(results[0].line_content) == 100

    def test_normal_line_not_truncated(self, tmp_path):
        (tmp_path / "ok.py").write_text("short line\n")

        engine = GrepEngine(
            tmp_path,
            [PurePosixPath("ok.py")],
            max_line_length=100,
        )
        results = engine.search("short")
        assert len(results) == 1
        assert results[0].line_content == "short line"


# =============================================================================
# B4 — Citation verifier file-size guard
# =============================================================================


class TestCitationFileSizeGuard:
    """B4: CitationVerifier skips files larger than 10 MB."""

    def test_large_file_skipped(self, tmp_path):
        from ingot.discovery.citation_verifier import CitationVerifier

        large_file = tmp_path / "huge.py"
        large_file.write_text("x")

        verifier = CitationVerifier(tmp_path)

        # Patch stat to report >10 MB
        original_stat = Path.stat

        def fake_stat(self_path):
            result = original_stat(self_path)
            if self_path.name == "huge.py":

                class FakeStat:
                    st_size = 20 * 1024 * 1024  # 20 MB
                    st_mode = result.st_mode  # keep real mode so is_file() works

                return FakeStat()
            return result

        with patch.object(Path, "stat", fake_stat):
            check = verifier._verify_single("huge.py", 1, 5, {"foo"})

        assert not check.is_verified
        assert "too large" in check.reason

    def test_normal_file_not_skipped(self, tmp_path):
        from ingot.discovery.citation_verifier import CitationVerifier

        normal_file = tmp_path / "small.py"
        normal_file.write_text("def foo():\n    pass\n")

        verifier = CitationVerifier(tmp_path)
        check = verifier._verify_single("small.py", 1, 2, {"foo"})
        assert check.is_verified


# =============================================================================
# R7 — Threshold regex precision
# =============================================================================


class TestThresholdRegexPrecision:
    """R7: Arbitrary comparisons (e.g., 'version > 3') should not match threshold."""

    def test_bare_comparison_no_match(self):
        v = OperationalCompletenessValidator()
        # Plan with metric keyword but only bare "> 3" — should NOT count as threshold
        plan = "## Summary\nAdd Prometheus metric.\nIf version > 3, use new API.\n"
        ctx = ValidationContext(ticket_signals=[])
        findings = v.validate(plan, ctx)
        # Should report missing threshold value
        assert any("threshold" in f.message for f in findings)

    def test_explicit_threshold_keyword_matches(self):
        v = OperationalCompletenessValidator()
        plan = (
            "## Summary\nAdd Prometheus metric.\n"
            "Set alert threshold 500\n"
            "query: rate(http_requests_total[5m]){job='api'}\n"
            "Escalation: runbook link\n"
        )
        ctx = ValidationContext(ticket_signals=[])
        findings = v.validate(plan, ctx)
        # No missing elements
        assert len(findings) == 0

    def test_metric_comparison_matches(self):
        v = OperationalCompletenessValidator()
        plan = (
            "## Summary\nAdd Prometheus metric.\n"
            "Alert when latency > 500\n"
            "query: rate(http_requests_total[5m]){job='api'}\n"
            "Escalation: runbook link\n"
        )
        ctx = ValidationContext(ticket_signals=[])
        findings = v.validate(plan, ctx)
        assert len(findings) == 0


# =============================================================================
# R8 — Manifest parser XML error
# =============================================================================


class TestManifestParserXmlError:
    """R8: Malformed pom.xml produces descriptive error, not raw ParseError."""

    def test_malformed_pom_handled(self, tmp_path):
        from ingot.discovery.manifest_parser import ManifestParser

        pom = tmp_path / "pom.xml"
        pom.write_text("<project><bad>")

        parser = ManifestParser(tmp_path)
        # parse() catches all exceptions — should not crash
        graph = parser.parse()
        # Falls through to unknown since maven parse fails
        assert graph.project_type == "unknown"

    def test_malformed_pom_error_message(self, tmp_path):
        import xml.etree.ElementTree as ET

        from ingot.discovery.manifest_parser import ManifestParser

        pom = tmp_path / "pom.xml"
        pom.write_text("<project><bad>")

        parser = ManifestParser(tmp_path)
        try:
            parser._parse_maven(pom)
            raise AssertionError("Should have raised")
        except ET.ParseError as exc:
            assert "Invalid XML" in str(exc)
            assert "pom.xml" in str(exc)


# =============================================================================
# R2 — run_local_discovery, build_file_index, verify_researcher_citations
# =============================================================================


class TestRunLocalDiscovery:
    """R2: Edge cases for _run_local_discovery."""

    def test_empty_keywords_returns_empty(self):
        from ingot.workflow.step1_plan import _run_local_discovery

        state = MagicMock()
        state.ticket.title = ""
        state.ticket.description = ""

        result = _run_local_discovery(state, Path("/tmp"), None)
        assert result == ""

    def test_exception_returns_empty(self):
        from ingot.workflow.step1_plan import _run_local_discovery

        state = MagicMock()
        state.ticket.title = "some keywords"
        state.ticket.description = "more text"

        # Pass a non-existent path to trigger an error in ContextBuilder
        result = _run_local_discovery(state, Path("/nonexistent/repo/path"), None)
        assert result == ""


class TestBuildFileIndex:
    """R2: Edge cases for _build_file_index."""

    def test_none_repo_returns_none(self):
        from ingot.workflow.step1_plan import _build_file_index

        assert _build_file_index(None) is None

    def test_non_git_dir_returns_none(self, tmp_path):
        from ingot.workflow.step1_plan import _build_file_index

        result = _build_file_index(tmp_path)
        # Non-git dir will produce empty FileIndex or None
        assert result is None


class TestVerifyResearcherCitations:
    """R2: Edge cases for _verify_researcher_citations."""

    def test_empty_input(self):
        from ingot.workflow.step1_plan import _verify_researcher_citations

        assert _verify_researcher_citations("", None) == ""
        assert _verify_researcher_citations("   ", Path("/tmp")) == "   "

    def test_no_repo_returns_input(self):
        from ingot.workflow.step1_plan import _verify_researcher_citations

        text = "Source: `foo.py:1-5`\n```\ndef foo(): pass\n```"
        assert _verify_researcher_citations(text, None) == text

    def test_exception_returns_input(self):
        from ingot.workflow.step1_plan import _verify_researcher_citations

        text = "Source: `foo.py:1-5`\n```\ndef foo(): pass\n```"
        # Non-existent repo — CitationVerifier annotates missing files
        # with CITATION_UNREADABLE rather than raising an exception.
        result = _verify_researcher_citations(text, Path("/nonexistent"))
        assert "CITATION_UNREADABLE" in result
        assert "file not found" in result
