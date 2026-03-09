"""Tests for ingot.discovery.manifest_parser module."""

import json
import textwrap

import pytest

from ingot.discovery.manifest_parser import (
    Dependency,
    ManifestParser,
    Module,
    ModuleGraph,
)

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def maven_repo(tmp_path):
    """Create a multi-module Maven project with parent + 2 child modules."""
    # Parent pom.xml
    parent_pom = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <artifactId>parent-app</artifactId>
            <modules>
                <module>core</module>
                <module>web</module>
            </modules>
        </project>
    """
    )
    (tmp_path / "pom.xml").write_text(parent_pom)

    # core sub-module
    (tmp_path / "core").mkdir()
    core_pom = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <artifactId>core-lib</artifactId>
        </project>
    """
    )
    (tmp_path / "core" / "pom.xml").write_text(core_pom)

    # web sub-module depends on core-lib
    (tmp_path / "web").mkdir()
    web_pom = textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <project xmlns="http://maven.apache.org/POM/4.0.0">
            <artifactId>web-app</artifactId>
            <dependencies>
                <dependency>
                    <groupId>com.example</groupId>
                    <artifactId>core-lib</artifactId>
                </dependency>
            </dependencies>
        </project>
    """
    )
    (tmp_path / "web" / "pom.xml").write_text(web_pom)

    return tmp_path


@pytest.fixture()
def gradle_repo(tmp_path):
    """Create a multi-module Gradle project with settings + sub-projects."""
    settings = textwrap.dedent(
        """\
        rootProject.name = 'my-gradle-app'
        include ':api'
        include ':common'
    """
    )
    (tmp_path / "settings.gradle").write_text(settings)

    # api sub-module depends on common
    (tmp_path / "api").mkdir()
    api_build = textwrap.dedent(
        """\
        dependencies {
            implementation project(':common')
        }
    """
    )
    (tmp_path / "api" / "build.gradle").write_text(api_build)

    # common sub-module (no project deps)
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "build.gradle").write_text("// no project deps\n")

    return tmp_path


@pytest.fixture()
def npm_repo(tmp_path):
    """Create an npm workspace project with glob and exact workspace entries."""
    root_pkg = {
        "name": "my-monorepo",
        "workspaces": [
            "packages/*",
            "tools/cli",
        ],
    }
    (tmp_path / "package.json").write_text(json.dumps(root_pkg))

    # Glob workspace: packages/alpha and packages/beta
    (tmp_path / "packages" / "alpha").mkdir(parents=True)
    (tmp_path / "packages" / "alpha" / "package.json").write_text(
        json.dumps({"name": "@mono/alpha"})
    )
    (tmp_path / "packages" / "beta").mkdir(parents=True)
    (tmp_path / "packages" / "beta" / "package.json").write_text(json.dumps({"name": "@mono/beta"}))

    # Exact workspace: tools/cli
    (tmp_path / "tools" / "cli").mkdir(parents=True)
    (tmp_path / "tools" / "cli" / "package.json").write_text(json.dumps({"name": "@mono/cli"}))

    return tmp_path


@pytest.fixture()
def go_repo(tmp_path):
    """Create a Go module project."""
    go_mod = textwrap.dedent(
        """\
        module github.com/example/myservice

        go 1.21

        require (
            github.com/gin-gonic/gin v1.9.0
        )
    """
    )
    (tmp_path / "go.mod").write_text(go_mod)
    return tmp_path


@pytest.fixture()
def python_pyproject_repo(tmp_path):
    """Create a Python project with pyproject.toml."""
    pyproject = textwrap.dedent(
        """\
        [project]
        name = "ingot"
        version = "0.1.0"
    """
    )
    (tmp_path / "pyproject.toml").write_text(pyproject)
    return tmp_path


@pytest.fixture()
def python_setupcfg_repo(tmp_path):
    """Create a Python project with setup.cfg."""
    setup_cfg = textwrap.dedent(
        """\
        [metadata]
        name = my-legacy-package
        version = 1.0.0
    """
    )
    (tmp_path / "setup.cfg").write_text(setup_cfg)
    return tmp_path


# ------------------------------------------------------------------
# Maven tests
# ------------------------------------------------------------------


class TestMavenParsing:
    """Test Maven multi-module parsing."""

    def test_detects_maven_project_type(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        assert graph.project_type == "maven"

    def test_discovers_parent_and_child_modules(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "parent-app" in names
        assert "core-lib" in names
        assert "web-app" in names
        assert len(graph.modules) == 3

    def test_parent_module_path_is_root(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        parent = next(m for m in graph.modules if m.name == "parent-app")
        assert parent.path == "."
        assert parent.manifest_file == "pom.xml"

    def test_child_module_paths(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        core = next(m for m in graph.modules if m.name == "core-lib")
        assert core.path == "core"
        web = next(m for m in graph.modules if m.name == "web-app")
        assert web.path == "web"

    def test_inter_module_dependency_edges(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        assert Dependency(source="web-app", target="core-lib") in graph.edges

    def test_no_self_dependency_edges(self, maven_repo):
        parser = ManifestParser(maven_repo)
        graph = parser.parse()
        for edge in graph.edges:
            assert edge.source != edge.target


# ------------------------------------------------------------------
# Gradle tests
# ------------------------------------------------------------------


class TestGradleParsing:
    """Test Gradle multi-module parsing."""

    def test_detects_gradle_project_type(self, gradle_repo):
        parser = ManifestParser(gradle_repo)
        graph = parser.parse()
        assert graph.project_type == "gradle"

    def test_discovers_root_and_subprojects(self, gradle_repo):
        parser = ManifestParser(gradle_repo)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "root" in names
        assert "api" in names
        assert "common" in names

    def test_gradle_project_dependency_edges(self, gradle_repo):
        parser = ManifestParser(gradle_repo)
        graph = parser.parse()
        assert Dependency(source="api", target="common") in graph.edges

    def test_gradle_include_with_parens(self, tmp_path):
        """Include directive using parenthesized form: include(':mod')."""
        settings = "include(':service')\n"
        (tmp_path / "settings.gradle").write_text(settings)
        (tmp_path / "service").mkdir()
        (tmp_path / "service" / "build.gradle").write_text("")
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "service" in names

    def test_gradle_nested_modules(self, tmp_path):
        """Include with colon-separated nested modules: ':services:api'."""
        settings = textwrap.dedent(
            """\
            rootProject.name = 'nested-app'
            include ':services:api', ':services:common'
        """
        )
        (tmp_path / "settings.gradle").write_text(settings)
        (tmp_path / "services" / "api").mkdir(parents=True)
        (tmp_path / "services" / "api" / "build.gradle").write_text("")
        (tmp_path / "services" / "common").mkdir(parents=True)
        (tmp_path / "services" / "common" / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "services:api" in names
        assert "services:common" in names
        # Paths should use '/' instead of ':'
        paths = {m.path for m in graph.modules}
        assert "services/api" in paths
        assert "services/common" in paths

    def test_gradle_nested_project_dependency(self, tmp_path):
        """project(':services:common') should create a dependency edge."""
        settings = textwrap.dedent(
            """\
            rootProject.name = 'nested-app'
            include ':services:api', ':services:common'
        """
        )
        (tmp_path / "settings.gradle").write_text(settings)
        (tmp_path / "services" / "api").mkdir(parents=True)
        api_build = textwrap.dedent(
            """\
            dependencies {
                implementation project(':services:common')
            }
        """
        )
        (tmp_path / "services" / "api" / "build.gradle").write_text(api_build)
        (tmp_path / "services" / "common").mkdir(parents=True)
        (tmp_path / "services" / "common" / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        assert Dependency(source="services:api", target="services:common") in graph.edges

    def test_single_module_gradle(self, tmp_path):
        """Single-module Gradle project (build.gradle, no settings.gradle)."""
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'\n")
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        assert graph.project_type == "gradle"
        assert len(graph.modules) == 1
        assert graph.modules[0].path == "."

    def test_gradle_three_level_nesting(self, tmp_path):
        """Three-level nested module: ':services:billing:internal'."""
        settings = textwrap.dedent(
            """\
            rootProject.name = 'deep-app'
            include ':services:billing:internal'
        """
        )
        (tmp_path / "settings.gradle").write_text(settings)
        (tmp_path / "services" / "billing" / "internal").mkdir(parents=True)
        (tmp_path / "services" / "billing" / "internal" / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "services:billing:internal" in names
        paths = {m.path for m in graph.modules}
        assert "services/billing/internal" in paths

    def test_gradle_kotlin_dsl_include_function(self, tmp_path):
        """settings.gradle.kts with include(\":api\") Kotlin DSL syntax."""
        settings = textwrap.dedent(
            """\
            rootProject.name = "kts-app"
            include(":api")
        """
        )
        (tmp_path / "settings.gradle.kts").write_text(settings)
        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "build.gradle.kts").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "api" in names
        # Should pick up .kts manifest file
        api_mod = next(m for m in graph.modules if m.name == "api")
        assert api_mod.manifest_file == "build.gradle.kts"

    def test_gradle_mixed_include_styles(self, tmp_path):
        """Mix of include ':a' and include(':b:c', ':b:d') on separate lines."""
        settings = textwrap.dedent(
            """\
            rootProject.name = 'mixed'
            include ':a'
            include(':b:c', ':b:d')
        """
        )
        (tmp_path / "settings.gradle").write_text(settings)
        for mod_path in ["a", "b/c", "b/d"]:
            (tmp_path / mod_path).mkdir(parents=True, exist_ok=True)
            (tmp_path / mod_path / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "a" in names
        assert "b:c" in names
        assert "b:d" in names

    def test_gradle_multiline_include(self, tmp_path):
        """Multiline include with parenthesized form spanning multiple lines."""
        settings = textwrap.dedent(
            """\
            rootProject.name = 'multi-line-app'
            include(
                ':api',
                ':common',
                ':worker'
            )
        """
        )
        (tmp_path / "settings.gradle").write_text(settings)
        for mod in ["api", "common", "worker"]:
            (tmp_path / mod).mkdir()
            (tmp_path / mod / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "api" in names
        assert "common" in names
        assert "worker" in names

    def test_gradle_module_with_dots(self, tmp_path):
        """Module name containing dots: ':com.example.service'."""
        settings = "include ':com.example.service'\n"
        (tmp_path / "settings.gradle").write_text(settings)
        # Dots don't map to directories in Gradle (they stay as-is)
        (tmp_path / "com.example.service").mkdir()
        (tmp_path / "com.example.service" / "build.gradle").write_text("")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "com.example.service" in names


# ------------------------------------------------------------------
# npm tests
# ------------------------------------------------------------------


class TestNpmParsing:
    """Test npm workspaces parsing."""

    def test_detects_npm_project_type(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        assert graph.project_type == "npm"

    def test_discovers_root_package(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        root = next(m for m in graph.modules if m.path == ".")
        assert root.name == "my-monorepo"

    def test_resolves_glob_workspaces(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "@mono/alpha" in names
        assert "@mono/beta" in names

    def test_resolves_exact_workspaces(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        names = {m.name for m in graph.modules}
        assert "@mono/cli" in names

    def test_total_module_count(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        # root + alpha + beta + cli = 4
        assert len(graph.modules) == 4

    def test_workspace_paths(self, npm_repo):
        parser = ManifestParser(npm_repo)
        graph = parser.parse()
        cli = next(m for m in graph.modules if m.name == "@mono/cli")
        assert cli.path == "tools/cli"
        assert cli.manifest_file == "package.json"


# ------------------------------------------------------------------
# Go tests
# ------------------------------------------------------------------


class TestGoParsing:
    """Test Go module parsing."""

    def test_detects_go_project_type(self, go_repo):
        parser = ManifestParser(go_repo)
        graph = parser.parse()
        assert graph.project_type == "go"

    def test_parses_module_path(self, go_repo):
        parser = ManifestParser(go_repo)
        graph = parser.parse()
        assert len(graph.modules) == 1
        assert graph.modules[0].name == "github.com/example/myservice"

    def test_module_path_is_root(self, go_repo):
        parser = ManifestParser(go_repo)
        graph = parser.parse()
        assert graph.modules[0].path == "."
        assert graph.modules[0].manifest_file == "go.mod"


# ------------------------------------------------------------------
# Python tests
# ------------------------------------------------------------------


class TestPythonParsing:
    """Test Python project parsing."""

    def test_pyproject_detects_python_type(self, python_pyproject_repo):
        parser = ManifestParser(python_pyproject_repo)
        graph = parser.parse()
        assert graph.project_type == "python"

    def test_pyproject_parses_name(self, python_pyproject_repo):
        parser = ManifestParser(python_pyproject_repo)
        graph = parser.parse()
        assert graph.modules[0].name == "ingot"
        assert graph.modules[0].manifest_file == "pyproject.toml"

    def test_setupcfg_parses_name(self, python_setupcfg_repo):
        parser = ManifestParser(python_setupcfg_repo)
        graph = parser.parse()
        assert graph.modules[0].name == "my-legacy-package"
        assert graph.modules[0].manifest_file == "setup.cfg"


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


class TestEdgeCases:
    """Test single-module, no-manifest, and error handling."""

    def test_no_manifest_returns_unknown(self, tmp_path):
        """When no manifest is found, project_type should be 'unknown'."""
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        assert graph.project_type == "unknown"
        assert graph.modules == []
        assert graph.edges == []

    def test_malformed_pom_handled_gracefully(self, tmp_path):
        """A malformed pom.xml should not raise; falls through to 'unknown'."""
        (tmp_path / "pom.xml").write_text("<<<not valid xml>>>")
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        # Parsing should fail gracefully and return unknown
        assert graph.project_type == "unknown"

    def test_malformed_package_json_handled_gracefully(self, tmp_path):
        """A malformed package.json should not raise; falls through to 'unknown'."""
        (tmp_path / "package.json").write_text("{bad json!!!")
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        assert graph.project_type == "unknown"

    def test_malformed_sub_module_pom_continues(self, tmp_path):
        """A malformed sub-module pom should not block the parent parse."""
        parent_pom = textwrap.dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <project>
                <artifactId>parent</artifactId>
                <modules>
                    <module>broken</module>
                </modules>
            </project>
        """
        )
        (tmp_path / "pom.xml").write_text(parent_pom)
        (tmp_path / "broken").mkdir()
        (tmp_path / "broken" / "pom.xml").write_text("<<<invalid xml>>>")

        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        # Should still parse the parent and the module directory name
        assert graph.project_type == "maven"
        names = {m.name for m in graph.modules}
        assert "parent" in names
        assert "broken" in names  # Falls back to directory name

    def test_empty_go_mod_uses_unknown_name(self, tmp_path):
        """go.mod without a module line uses 'unknown' as the module name."""
        (tmp_path / "go.mod").write_text("go 1.21\n")
        parser = ManifestParser(tmp_path)
        graph = parser.parse()
        assert graph.project_type == "go"
        assert graph.modules[0].name == "unknown"


# ------------------------------------------------------------------
# ModuleGraph.to_markdown()
# ------------------------------------------------------------------


class TestModuleGraphMarkdown:
    """Test the to_markdown() output format."""

    def test_empty_modules_returns_empty(self):
        graph = ModuleGraph(project_type="unknown")
        assert graph.to_markdown() == ""

    def test_markdown_includes_project_type(self):
        graph = ModuleGraph(
            project_type="maven",
            modules=[Module(name="app", path=".", manifest_file="pom.xml")],
        )
        md = graph.to_markdown()
        assert "**Project type**: maven" in md

    def test_markdown_includes_dependencies(self):
        graph = ModuleGraph(
            project_type="gradle",
            modules=[
                Module(name="api", path="api", manifest_file="build.gradle"),
                Module(name="common", path="common", manifest_file="build.gradle"),
            ],
            edges=[Dependency(source="api", target="common")],
        )
        md = graph.to_markdown()
        assert "`api` \u2192 `common`" in md
        assert "**Dependencies** (1):" in md
