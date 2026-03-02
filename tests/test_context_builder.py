"""Tests for ingot.discovery.context_builder module."""

from pathlib import PurePosixPath
from unittest.mock import MagicMock, patch

from ingot.discovery.context_builder import (
    ContextBuilder,
    LocalDiscoveryReport,
    extract_keywords,
)
from ingot.discovery.grep_engine import GrepMatch, SearchMeta, SearchResult
from ingot.discovery.manifest_parser import Module, ModuleGraph

# ------------------------------------------------------------------
# extract_keywords tests
# ------------------------------------------------------------------


class TestExtractKeywords:
    """Test keyword extraction from ticket text."""

    def test_extracts_pascal_case(self):
        result = extract_keywords("Fix the FooService and BarController")
        assert "FooService" in result
        assert "BarController" in result

    def test_extracts_camel_case(self):
        result = extract_keywords("Update checkAndAlert logic")
        assert "checkAndAlert" in result

    def test_extracts_dotted_identifiers(self):
        result = extract_keywords("Change app.config and db.settings")
        assert "app.config" in result
        assert "db.settings" in result

    def test_dedup_preserves_order(self):
        result = extract_keywords("FooService and FooService again, BarHelper then BarHelper")
        assert result == ["FooService", "BarHelper"]

    def test_dedup_is_case_insensitive(self):
        """Same word in different cases should be deduplicated."""
        result = extract_keywords("FooService and fooservice and FOOSERVICE")
        # Only the first occurrence should remain
        assert len([kw for kw in result if kw.lower() == "fooservice"]) == 1

    def test_empty_text_returns_empty(self):
        assert extract_keywords("") == []

    def test_none_like_text_returns_empty(self):
        """Non-matching plain text returns empty."""
        assert extract_keywords("no identifiers here at all") == []

    def test_max_keywords_limit(self):
        # Generate text with many identifiers
        identifiers = [f"Keyword{i:03d}" for i in range(50)]
        text = " ".join(identifiers)
        result = extract_keywords(text, max_keywords=5)
        assert len(result) == 5

    def test_max_keywords_default_is_20(self):
        identifiers = [f"Identifier{i:03d}" for i in range(30)]
        text = " ".join(identifiers)
        result = extract_keywords(text)
        assert len(result) <= 20

    def test_short_pascal_case_excluded(self):
        """PascalCase words shorter than 4 chars are excluded by regex."""
        result = extract_keywords("Fix the Foo and Bar")
        # "Foo" and "Bar" are only 3 chars - regex requires 4+
        assert "Foo" not in result
        assert "Bar" not in result

    def test_extracts_tech_acronyms(self):
        """Short all-caps tech acronyms should be extracted."""
        result = extract_keywords("Fix AWS SQS integration")
        assert "AWS" in result
        assert "SQS" in result

    def test_extracts_mixed_alphanumeric_acronyms(self):
        """Acronyms with digits like EC2, S3 should be extracted."""
        result = extract_keywords("Deploy to EC2 and S3")
        assert "EC2" in result
        assert "S3" in result

    def test_filters_english_acronym_stopwords(self):
        """Common English all-caps words should be filtered out."""
        result = extract_keywords("THE FIX FOR BUG")
        assert "THE" not in result
        assert "FIX" not in result
        assert "FOR" not in result
        assert "BUG" not in result

    def test_acronym_does_not_break_pascal_case(self):
        """PascalCase starting with acronym should still match as PascalCase."""
        result = extract_keywords("AWSService handles requests")
        assert "AWSService" in result


# ------------------------------------------------------------------
# LocalDiscoveryReport.is_empty
# ------------------------------------------------------------------


class TestLocalDiscoveryReportIsEmpty:
    """Test the is_empty property."""

    def test_empty_when_no_data(self):
        report = LocalDiscoveryReport()
        assert report.is_empty is True

    def test_not_empty_with_keyword_matches(self):
        report = LocalDiscoveryReport(
            keyword_matches={
                "Foo": [
                    GrepMatch(
                        file=PurePosixPath("src/Foo.java"),
                        line_num=10,
                        line_content="class Foo {",
                    )
                ]
            }
        )
        assert report.is_empty is False

    def test_not_empty_with_module_graph(self):
        graph = ModuleGraph(
            project_type="maven",
            modules=[Module(name="app", path=".", manifest_file="pom.xml")],
        )
        report = LocalDiscoveryReport(module_graph=graph)
        assert report.is_empty is False

    def test_empty_with_module_graph_no_modules(self):
        """A graph with no modules is still considered empty."""
        graph = ModuleGraph(project_type="unknown")
        report = LocalDiscoveryReport(module_graph=graph)
        assert report.is_empty is True

    def test_not_empty_with_test_mappings(self):
        report = LocalDiscoveryReport(
            test_mappings={
                "src/foo.py": [PurePosixPath("tests/test_foo.py")],
            }
        )
        assert report.is_empty is False


# ------------------------------------------------------------------
# LocalDiscoveryReport.to_markdown
# ------------------------------------------------------------------


class TestLocalDiscoveryReportMarkdown:
    """Test the to_markdown() formatting."""

    def test_empty_report_returns_empty_string(self):
        report = LocalDiscoveryReport()
        assert report.to_markdown() == ""

    def test_includes_module_structure_section(self):
        graph = ModuleGraph(
            project_type="maven",
            modules=[Module(name="core", path="core", manifest_file="pom.xml")],
        )
        report = LocalDiscoveryReport(module_graph=graph)
        md = report.to_markdown()
        assert "#### Module Structure" in md
        assert "maven" in md
        assert "`core`" in md

    def test_includes_keyword_matches_section(self):
        report = LocalDiscoveryReport(
            keyword_matches={
                "FooService": [
                    GrepMatch(
                        file=PurePosixPath("src/FooService.java"),
                        line_num=5,
                        line_content="public class FooService {",
                    ),
                ]
            }
        )
        md = report.to_markdown()
        assert "#### Keyword Matches" in md
        assert "**`FooService`**" in md
        assert "1 match)" in md
        assert "`src/FooService.java:5`" in md

    def test_keyword_matches_pluralization(self):
        """Multiple matches should use 'matches' plural."""
        matches = [
            GrepMatch(
                file=PurePosixPath(f"src/File{i}.java"),
                line_num=i,
                line_content=f"line {i}",
            )
            for i in range(3)
        ]
        report = LocalDiscoveryReport(keyword_matches={"Foo": matches})
        md = report.to_markdown()
        assert "3 matches)" in md

    def test_includes_test_mappings_section(self):
        report = LocalDiscoveryReport(
            test_mappings={
                "src/foo.py": [PurePosixPath("tests/test_foo.py")],
            }
        )
        md = report.to_markdown()
        assert "#### Test File Mappings" in md
        assert "`src/foo.py`" in md
        assert "`tests/test_foo.py`" in md

    def test_budget_truncation(self):
        """Report should be truncated when exceeding budget."""
        matches = [
            GrepMatch(
                file=PurePosixPath(f"src/very/long/path/File{i}.java"),
                line_num=i,
                line_content=f"some matching content on line {i} that is fairly verbose",
            )
            for i in range(100)
        ]
        report = LocalDiscoveryReport(keyword_matches={"BigKeyword": matches})
        md = report.to_markdown(budget=200)
        assert len(md) <= 200
        assert "... [truncated]" in md

    def test_full_report_with_all_sections(self):
        """A report with all three sections should have all headings."""
        graph = ModuleGraph(
            project_type="gradle",
            modules=[Module(name="app", path=".", manifest_file="build.gradle")],
        )
        report = LocalDiscoveryReport(
            module_graph=graph,
            keyword_matches={
                "Handler": [
                    GrepMatch(
                        file=PurePosixPath("src/Handler.java"),
                        line_num=1,
                        line_content="class Handler",
                    )
                ]
            },
            test_mappings={
                "src/Handler.java": [PurePosixPath("test/HandlerTest.java")],
            },
        )
        md = report.to_markdown()
        assert "#### Module Structure" in md
        assert "#### Keyword Matches" in md
        assert "#### Test File Mappings" in md


# ------------------------------------------------------------------
# ContextBuilder.build
# ------------------------------------------------------------------


def _make_mock_file_index(file_count: int = 5, paths: list[str] | None = None):
    """Create a mock FileIndex with configurable file_count and paths."""
    idx = MagicMock()
    idx.file_count = file_count
    if paths is None:
        paths = [f"src/File{i}.java" for i in range(file_count)]
    idx.all_paths.return_value = [PurePosixPath(p) for p in paths]
    idx.find_by_stem.return_value = []
    return idx


def _make_search_result(
    matches: list[GrepMatch],
    *,
    was_truncated: bool = False,
    truncation_reason: str | None = None,
) -> SearchResult:
    """Create a SearchResult for mocking search_batch_with_meta."""
    return SearchResult(
        matches=matches,
        meta=SearchMeta(
            total_matches_found=len(matches),
            files_searched=1,
            files_total=1,
            was_truncated=was_truncated,
            truncation_reason=truncation_reason,
        ),
    )


class TestContextBuilderBuild:
    """Test ContextBuilder.build() orchestration."""

    def test_build_with_empty_file_index_returns_early(self, tmp_path):
        """When FileIndex has 0 files, build should return early."""
        builder = ContextBuilder(tmp_path)
        empty_index = _make_mock_file_index(file_count=0)
        report = builder.build(file_index=empty_index)
        assert report.file_index is empty_index
        assert report.is_empty

    def test_build_stores_file_index(self, tmp_path):
        """Build should attach the file_index to the report."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()
        with patch("ingot.discovery.context_builder.ManifestParser") as MockParser:
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            report = builder.build(file_index=idx)
        assert report.file_index is idx

    def test_build_calls_manifest_parser(self, tmp_path):
        """Build should invoke ManifestParser.parse()."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()
        with patch("ingot.discovery.context_builder.ManifestParser") as MockParser:
            mock_graph = ModuleGraph(
                project_type="maven",
                modules=[Module(name="app", path=".", manifest_file="pom.xml")],
            )
            MockParser.return_value.parse.return_value = mock_graph
            report = builder.build(file_index=idx)
        assert report.module_graph is mock_graph

    def test_build_runs_grep_for_keywords(self, tmp_path):
        """Build should grep for provided keywords."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index(paths=["src/Foo.java"])

        mock_grep_match = GrepMatch(
            file=PurePosixPath("src/Foo.java"),
            line_num=10,
            line_content="class Foo {",
        )

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([mock_grep_match]),
            }
            MockMapper.return_value.map_all.return_value = {}

            report = builder.build(keywords=["Foo"], file_index=idx)

        assert "Foo" in report.keyword_matches
        assert len(report.keyword_matches["Foo"]) == 1
        assert report.keywords_used == ["Foo"]

    def test_build_runs_test_mapper_on_grep_results(self, tmp_path):
        """Build should map source files from grep results to test files."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index(paths=["src/Foo.java"])

        mock_match = GrepMatch(
            file=PurePosixPath("src/Foo.java"),
            line_num=1,
            line_content="class Foo",
        )
        mock_test_map = {
            "src/Foo.java": [PurePosixPath("test/FooTest.java")],
        }

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([mock_match]),
            }
            MockMapper.return_value.map_all.return_value = mock_test_map

            report = builder.build(keywords=["Foo"], file_index=idx)

        assert "src/Foo.java" in report.test_mappings
        assert PurePosixPath("test/FooTest.java") in report.test_mappings["src/Foo.java"]

    def test_build_without_keywords_skips_grep(self, tmp_path):
        """When no keywords are given, grep and test mapping are skipped."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            report = builder.build(file_index=idx)

        MockGrep.assert_not_called()
        assert report.keyword_matches == {}
        assert report.test_mappings == {}

    def test_build_handles_manifest_parser_failure(self, tmp_path):
        """ManifestParser failure should not crash build."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()

        with patch("ingot.discovery.context_builder.ManifestParser") as MockParser:
            MockParser.return_value.parse.side_effect = RuntimeError("parse boom")
            report = builder.build(file_index=idx)

        # Should not raise; module_graph stays None
        assert report.module_graph is None

    def test_build_handles_grep_engine_failure(self, tmp_path):
        """GrepEngine failure should not crash build."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.side_effect = RuntimeError("grep boom")

            report = builder.build(keywords=["Foo"], file_index=idx)

        # Should not raise; keyword_matches stays empty
        assert report.keyword_matches == {}

    def test_build_handles_test_mapper_failure(self, tmp_path):
        """TestMapper failure should not crash build."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index()

        mock_match = GrepMatch(
            file=PurePosixPath("src/Foo.java"),
            line_num=1,
            line_content="class Foo",
        )

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([mock_match]),
            }
            MockMapper.return_value.map_all.side_effect = RuntimeError("mapper boom")

            report = builder.build(keywords=["Foo"], file_index=idx)

        # Should not raise; test_mappings stays empty
        assert report.test_mappings == {}

    def test_build_creates_file_index_when_not_provided(self, tmp_path):
        """When file_index is None, build creates one via FileIndex(repo_root)."""
        builder = ContextBuilder(tmp_path)

        mock_idx = _make_mock_file_index(file_count=0)
        with patch("ingot.discovery.context_builder.FileIndex", return_value=mock_idx) as MockFI:
            report = builder.build()

        MockFI.assert_called_once_with(tmp_path.resolve())
        assert report.file_index is mock_idx

    def test_build_handles_file_index_construction_failure(self, tmp_path):
        """If FileIndex construction fails, build returns empty report."""
        builder = ContextBuilder(tmp_path)

        with patch("ingot.discovery.context_builder.FileIndex", side_effect=RuntimeError("no git")):
            report = builder.build()

        assert report.file_index is None
        assert report.is_empty


# ------------------------------------------------------------------
# Truncation reporting (Issue 2)
# ------------------------------------------------------------------


class TestTruncationReporting:
    """Test truncation metadata propagation from GrepEngine to report."""

    def test_context_builder_reports_truncation(self, tmp_path):
        """When grep results are truncated, the report should reflect it."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index(paths=["src/Foo.java"])

        mock_match = GrepMatch(
            file=PurePosixPath("src/Foo.java"),
            line_num=1,
            line_content="class Foo",
        )

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result(
                    [mock_match], was_truncated=True, truncation_reason="max_total"
                ),
            }
            MockMapper.return_value.map_all.return_value = {}

            report = builder.build(keywords=["Foo"], file_index=idx)

        assert report.was_truncated is True
        assert "max_total" in report.truncation_reasons
        md = report.to_markdown()
        assert "truncated" in md.lower()
        assert "max_total" in md

    def test_no_truncation_when_under_limits(self, tmp_path):
        """When grep is not truncated, report should show was_truncated=False."""
        builder = ContextBuilder(tmp_path)
        idx = _make_mock_file_index(paths=["src/Foo.java"])

        mock_match = GrepMatch(
            file=PurePosixPath("src/Foo.java"),
            line_num=1,
            line_content="class Foo",
        )

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([mock_match]),
            }
            MockMapper.return_value.map_all.return_value = {}

            report = builder.build(keywords=["Foo"], file_index=idx)

        assert report.was_truncated is False
        assert report.truncation_reasons == []

    def test_truncation_markdown_note_only_when_truncated(self):
        """Markdown should only include truncation note when was_truncated=True."""
        report = LocalDiscoveryReport(
            keyword_matches={
                "Foo": [
                    GrepMatch(
                        file=PurePosixPath("src/Foo.java"),
                        line_num=1,
                        line_content="class Foo",
                    )
                ]
            },
            was_truncated=False,
        )
        md = report.to_markdown()
        assert "truncated" not in md.lower() or "... [truncated]" in md  # budget trunc is OK

    def test_truncation_markdown_note_present_when_truncated(self):
        """Markdown should include truncation note when was_truncated=True."""
        report = LocalDiscoveryReport(
            keyword_matches={
                "Foo": [
                    GrepMatch(
                        file=PurePosixPath("src/Foo.java"),
                        line_num=1,
                        line_content="class Foo",
                    )
                ]
            },
            was_truncated=True,
            truncation_reasons=["max_total"],
        )
        md = report.to_markdown()
        assert "> **Note**: Search results were truncated" in md


# ------------------------------------------------------------------
# Config knobs (Issue 7)
# ------------------------------------------------------------------


class TestContextBuilderConfig:
    """Test ContextBuilder custom configuration parameters."""

    def test_custom_grep_config(self, tmp_path):
        """Custom grep config should be passed through to GrepEngine."""
        builder = ContextBuilder(
            tmp_path,
            grep_max_per_file=10,
            grep_max_total=200,
            grep_timeout=60.0,
        )
        idx = _make_mock_file_index(paths=["src/Foo.java"])

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([]),
            }
            MockMapper.return_value.map_all.return_value = {}

            builder.build(keywords=["Foo"], file_index=idx)

        # Verify GrepEngine was constructed with custom config
        call_kwargs = MockGrep.call_args
        assert call_kwargs.kwargs["max_matches_per_file"] == 10
        assert call_kwargs.kwargs["max_matches_total"] == 200
        assert call_kwargs.kwargs["search_timeout"] == 60.0

    def test_custom_large_repo_threshold(self, tmp_path):
        """Custom large_repo_threshold should control when scoping kicks in."""
        builder = ContextBuilder(tmp_path, large_repo_threshold=3)
        # Index with 5 files — exceeds threshold of 3
        idx = _make_mock_file_index(file_count=5)

        with (
            patch("ingot.discovery.context_builder.ManifestParser") as MockParser,
            patch("ingot.discovery.context_builder.GrepEngine") as MockGrep,
            patch("ingot.discovery.context_builder.TestMapper") as MockMapper,
        ):
            MockParser.return_value.parse.return_value = ModuleGraph(project_type="unknown")
            MockGrep.return_value.search_batch_with_meta.return_value = {
                "Foo": _make_search_result([]),
            }
            MockMapper.return_value.map_all.return_value = {}

            builder.build(keywords=["Foo"], file_index=idx)

        # GrepEngine should have been called (scoping attempted but falls back)
        MockGrep.assert_called_once()
