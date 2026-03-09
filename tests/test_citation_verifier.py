"""Tests for ingot.discovery.citation_verifier module."""

import pytest

from ingot.discovery.citation_verifier import CitationVerifier


@pytest.fixture()
def sample_repo(tmp_path):
    """Create a sample repository with source files for citation testing."""
    (tmp_path / "src" / "main").mkdir(parents=True)

    (tmp_path / "src" / "main" / "MetricsHelper.java").write_text(
        "package com.example;\n"
        "\n"
        "import io.micrometer.core.instrument.DistributionSummary;\n"
        "import io.micrometer.core.instrument.MeterRegistry;\n"
        "\n"
        "public class MetricsHelper {\n"
        "    private final MeterRegistry registry;\n"
        "\n"
        "    public MetricsHelper(MeterRegistry registry) {\n"
        "        this.registry = registry;\n"
        "    }\n"
        "\n"
        "    public void recordMetric(String name, double value) {\n"
        "        DistributionSummary.builder(name)\n"
        "            .register(registry)\n"
        "            .record(value);\n"
        "    }\n"
        "}\n"
    )

    (tmp_path / "src" / "main" / "GaugeMonitor.java").write_text(
        "package com.example;\n"
        "\n"
        "import io.micrometer.core.instrument.Gauge;\n"
        "import java.util.concurrent.atomic.AtomicInteger;\n"
        "\n"
        "public class GaugeMonitor {\n"
        "    private final AtomicInteger counter = new AtomicInteger(0);\n"
        "\n"
        "    public void register(MeterRegistry registry) {\n"
        '        Gauge.builder("my.gauge", counter, AtomicInteger::get)\n'
        "            .register(registry);\n"
        "    }\n"
        "}\n"
    )

    return tmp_path


class TestCitationVerifierValid:
    """Test verification of valid citations."""

    def test_valid_citation_is_verified(self, sample_repo):
        """Citation matching actual file content should be verified."""
        researcher_output = """\
### Existing Code Patterns
#### Pattern: Distribution Summary Metrics
Source: `src/main/MetricsHelper.java:13-17`
```java
    public void recordMetric(String name, double value) {
        DistributionSummary.builder(name)
            .register(registry)
            .record(value);
    }
```
Why relevant: Shows how to register metrics."""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert checks[0].is_verified
        assert "CITATION_VERIFIED" in annotated

    def test_gauge_citation_verified(self, sample_repo):
        """Gauge pattern citation should be verified against correct file."""
        researcher_output = """\
#### Pattern: Gauge Registration
Source: `src/main/GaugeMonitor.java:9-12`
```java
    public void register(MeterRegistry registry) {
        Gauge.builder("my.gauge", counter, AtomicInteger::get)
            .register(registry);
    }
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert checks[0].is_verified


class TestCitationVerifierMismatch:
    """Test detection of citation mismatches."""

    def test_wrong_api_detected(self, sample_repo):
        """Citing MetricsHelper but claiming it uses Gauge should mismatch at strict threshold."""
        researcher_output = """\
#### Pattern: Gauge Metric
Source: `src/main/MetricsHelper.java:13-17`
```java
    public void recordMetric(String name, double value) {
        Gauge.builder(name, () -> value)
            .register(registry);
    }
```"""

        # Use strict threshold: snippet contains "Gauge" but file has "DistributionSummary"
        verifier = CitationVerifier(sample_repo, overlap_threshold=0.9)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert checks[0].is_verified is False
        assert "CITATION_MISMATCH" in annotated


class TestCitationVerifierErrors:
    """Test error handling in citation verification."""

    def test_file_not_found(self, sample_repo):
        """Missing file should be annotated as unreadable."""
        researcher_output = """\
#### Pattern: Something
Source: `src/main/NonExistent.java:1-5`
```java
    public void doSomething() {
        SomeClass obj = new SomeClass();
    }
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert not checks[0].is_verified
        assert "file not found" in checks[0].reason

    def test_line_range_out_of_bounds(self, sample_repo):
        """Line range beyond file end should be annotated."""
        researcher_output = """\
#### Pattern: Out of Bounds
Source: `src/main/MetricsHelper.java:500-510`
```java
    public void farAway() {
        Something.doStuff();
    }
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert not checks[0].is_verified
        assert "out of bounds" in checks[0].reason

    def test_no_code_block_near_citation_skipped(self, sample_repo):
        """Citation without adjacent code block should be skipped."""
        researcher_output = """\
#### Pattern: No Code
Source: `src/main/MetricsHelper.java:1-5`
Why relevant: Some explanation without a code block."""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 0

    def test_single_line_citation(self, sample_repo):
        """Citation with a single line (no range) should work."""
        researcher_output = """\
#### Pattern: Single Line
Source: `src/main/MetricsHelper.java:6`
```java
public class MetricsHelper {
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert checks[0].start_line == 6
        assert checks[0].end_line == 6


class TestCitationVerifierMultiple:
    """Test multiple citations in one output."""

    def test_multiple_citations(self, sample_repo):
        """Multiple citations should all be checked."""
        researcher_output = """\
### Existing Code Patterns
#### Pattern: Distribution Summary
Source: `src/main/MetricsHelper.java:13-17`
```java
    public void recordMetric(String name, double value) {
        DistributionSummary.builder(name)
            .register(registry)
            .record(value);
    }
```

#### Pattern: Gauge Registration
Source: `src/main/GaugeMonitor.java:9-12`
```java
    public void register(MeterRegistry registry) {
        Gauge.builder("my.gauge", counter, AtomicInteger::get)
            .register(registry);
    }
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 2

    def test_empty_output_returns_unchanged(self, sample_repo):
        """Empty researcher output returns unchanged."""
        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations("")
        assert annotated == ""
        assert checks == []

    def test_no_citations_returns_unchanged(self, sample_repo):
        """Output without citations returns unchanged."""
        researcher_output = "### Verified Files\n- `src/main/MetricsHelper.java`"
        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)
        assert annotated == researcher_output
        assert checks == []


class TestCitationVerifierPathTraversal:
    """Test path traversal protection."""

    def test_traversal_blocked(self, sample_repo):
        """Citation with ../../ path traversal should be blocked."""
        researcher_output = """\
#### Pattern: Traversal
Source: `../../etc/config.txt:1-5`
```java
public class SecretConfig {
    DistributionSummary.builder("test").register(registry);
}
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert not checks[0].is_verified
        assert "path traversal blocked" in checks[0].reason

    def test_absolute_path_blocked(self, sample_repo):
        """Citation with absolute path should be blocked."""
        researcher_output = """\
#### Pattern: Absolute
Source: `/etc/config.txt:1-3`
```java
public class SecretConfig {
    SomeClass obj = new SomeClass();
}
```"""

        verifier = CitationVerifier(sample_repo)
        annotated, checks = verifier.verify_citations(researcher_output)

        assert len(checks) == 1
        assert not checks[0].is_verified
        assert "path traversal blocked" in checks[0].reason


class TestCitationThresholds:
    """Test threshold variation affects verification outcome."""

    def test_strict_threshold_rejects_partial_match(self, sample_repo):
        """With overlap_threshold=1.0, a partial match should fail."""
        researcher_output = """\
#### Pattern: Distribution Summary Metrics
Source: `src/main/MetricsHelper.java:13-17`
```java
    public void recordMetric(String name, double value) {
        DistributionSummary.builder(name)
            .register(registry)
            .record(value);
    }
```"""
        verifier = CitationVerifier(sample_repo, overlap_threshold=1.0)
        _, checks = verifier.verify_citations(researcher_output)
        assert len(checks) == 1
        # The snippet text is identical to the actual file content at lines
        # 13-17, so all identifiers overlap and the strict threshold is met.
        assert checks[0].is_verified is True

    def test_permissive_threshold_accepts_any(self, sample_repo):
        """With overlap_threshold=0.0, even a mismatch should pass."""
        researcher_output = """\
#### Pattern: Gauge Metric
Source: `src/main/MetricsHelper.java:13-17`
```java
    public void recordMetric(String name, double value) {
        Gauge.builder(name, () -> value)
            .register(registry);
    }
```"""
        verifier = CitationVerifier(sample_repo, overlap_threshold=0.0)
        _, checks = verifier.verify_citations(researcher_output)
        assert len(checks) == 1
        assert checks[0].is_verified is True
