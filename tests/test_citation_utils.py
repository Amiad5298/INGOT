"""Tests for ingot.discovery.citation_utils module."""

from ingot.discovery.citation_utils import (
    extract_identifiers,
    safe_resolve_path,
)

# ------------------------------------------------------------------
# safe_resolve_path
# ------------------------------------------------------------------


class TestSafeResolvePath:
    """Tests for safe_resolve_path."""

    def test_normal_path_resolves(self, tmp_path):
        """A valid relative path inside the repo resolves correctly."""
        (tmp_path / "src").mkdir()
        target = tmp_path / "src" / "Foo.java"
        target.write_text("class Foo {}")

        result = safe_resolve_path(tmp_path, "src/Foo.java")
        assert result is not None
        assert result == target.resolve()

    def test_traversal_returns_none(self, tmp_path):
        """Path traversal with ../../ is rejected."""
        result = safe_resolve_path(tmp_path, "../../../etc/passwd")
        assert result is None

    def test_absolute_returns_none(self, tmp_path):
        """Absolute paths are rejected."""
        result = safe_resolve_path(tmp_path, "/etc/passwd")
        assert result is None

    def test_backslash_absolute_returns_none(self, tmp_path):
        """Backslash-prefixed paths are rejected."""
        result = safe_resolve_path(tmp_path, "\\etc\\passwd")
        assert result is None

    def test_empty_string_returns_none(self, tmp_path):
        """Empty file_path is rejected."""
        result = safe_resolve_path(tmp_path, "")
        assert result is None

    def test_null_byte_returns_none(self, tmp_path):
        """Paths with null bytes are rejected."""
        result = safe_resolve_path(tmp_path, "src/foo\x00.py")
        assert result is None

    def test_symlink_escape_returns_none(self, tmp_path):
        """Symlink pointing outside repo root is rejected."""
        link = tmp_path / "escape_link"
        link.symlink_to("/tmp")
        result = safe_resolve_path(tmp_path, "escape_link/something")
        assert result is None

    def test_nested_path_resolves(self, tmp_path):
        """Deeply nested relative path inside repo resolves correctly."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        target = nested / "file.txt"
        target.write_text("content")

        result = safe_resolve_path(tmp_path, "a/b/c/file.txt")
        assert result is not None
        assert result == target.resolve()


# ------------------------------------------------------------------
# extract_identifiers
# ------------------------------------------------------------------


class TestExtractIdentifiers:
    """Tests for extract_identifiers and IDENTIFIER_RE."""

    def test_annotations(self):
        """@Component and similar annotations are extracted."""
        ids = extract_identifiers("@Component\n@Service\npublic class Foo {}")
        assert "@Component" in ids
        assert "@Service" in ids

    def test_pascal_case(self):
        """PascalCase identifiers (3+ chars) are extracted."""
        ids = extract_identifiers("DistributionSummary summary = new DistributionSummary();")
        assert "DistributionSummary" in ids

    def test_dotted_method(self):
        """Dotted method calls are extracted WITHOUT the trailing '('."""
        ids = extract_identifiers("builder.register(registry)")
        assert "builder.register" in ids
        # The paren should NOT be included
        assert "builder.register(" not in ids

    def test_function_call(self):
        """Plain function calls are extracted."""
        ids = extract_identifiers("register_metric(name, value)")
        assert "register_metric" in ids

    def test_empty_text(self):
        """Empty text returns empty set."""
        assert extract_identifiers("") == set()

    def test_short_pascal_case_excluded(self):
        """Two-char PascalCase words (like 'Ok') are excluded (need 3+ chars)."""
        ids = extract_identifiers("Ok value = process();")
        assert "Ok" not in ids

    def test_pascal_stopwords_filtered(self):
        """Common English words matching PascalCase are filtered out."""
        ids = extract_identifiers("The New class This That And But For Not")
        for word in ("The", "New", "This", "That", "And", "But", "For", "Not"):
            assert word not in ids

    def test_real_identifiers_not_filtered(self):
        """Real PascalCase identifiers survive stopword filtering."""
        ids = extract_identifiers("FooService BarHelper BazConfig")
        assert "FooService" in ids
        assert "BarHelper" in ids
        assert "BazConfig" in ids


# ------------------------------------------------------------------
# Cross-validator tests (Issue 6)
# ------------------------------------------------------------------


class TestCitationCrossValidation:
    """Verify both validators produce identical identifier sets from same input."""

    def test_same_identifiers_extracted(self):
        """Both CitationContentValidator and PatternSourceValidator
        use the same IDENTIFIER_RE, so identical text should yield
        identical identifier sets."""
        from ingot.discovery.citation_utils import IDENTIFIER_RE

        snippet = """\
@Component
public class FooService {
    private final DistributionSummary summary;
    public void register_metric(String name) {
        builder.register(registry);
    }
}
"""
        ids = set(IDENTIFIER_RE.findall(snippet))
        assert "@Component" in ids
        assert "FooService" in ids
        assert "DistributionSummary" in ids
        assert "builder.register" in ids
        assert "register_metric" in ids

    def test_citation_formats_intentionally_different(self):
        """The two citation regex patterns match their own format, not the other."""
        import re

        # PatternSourceValidator's regex
        pattern_source_re = re.compile(
            r"Pattern\s+source:\s*`?([^`\n]+?\.\w{1,8}):(\d+)(?:-(\d+))?`?",
            re.IGNORECASE,
        )
        # CitationVerifier uses "Source: <file>" — a different pattern
        source_re = re.compile(r"Source:\s*`?([^`\n]+?\.\w{1,8})`?")

        pattern_source_text = "Pattern source: src/Foo.java:10-20"
        source_text = "Source: src/Foo.java"

        # Each regex matches its own format
        assert pattern_source_re.search(pattern_source_text) is not None
        assert source_re.search(source_text) is not None

        # And does NOT match the other's format
        assert pattern_source_re.search(source_text) is None
        assert source_re.search(pattern_source_text) is None
