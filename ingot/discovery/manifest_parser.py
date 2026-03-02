"""Build manifest analysis for INGOT codebase discovery.

Detects project type by finding manifest files (pom.xml, build.gradle,
package.json, go.mod, pyproject.toml, etc.), parses multi-module structure
and inter-module dependency declarations.

Output: :class:`ModuleGraph` dataclass with modules and dependency edges.
"""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree as SafeET

from ingot.utils.logging import log_message


@dataclass(frozen=True)
class Module:
    """A single module/package in a multi-module project."""

    name: str
    path: str  # Relative path from repo root
    manifest_file: str  # e.g. "pom.xml", "build.gradle"


@dataclass(frozen=True)
class Dependency:
    """A dependency edge between modules."""

    source: str  # Module name that declares the dependency
    target: str  # Module name being depended upon


@dataclass
class ModuleGraph:
    """Dependency graph for a multi-module project."""

    project_type: str  # "maven", "gradle", "npm", "go", "python", "unknown"
    modules: list[Module] = field(default_factory=list)
    edges: list[Dependency] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Format the module graph as markdown for prompt injection."""
        if not self.modules:
            return ""

        lines = [f"**Project type**: {self.project_type}"]
        lines.append(f"**Modules** ({len(self.modules)}):")
        for mod in self.modules:
            lines.append(f"  - `{mod.name}` at `{mod.path}` ({mod.manifest_file})")

        if self.edges:
            lines.append(f"**Dependencies** ({len(self.edges)}):")
            for edge in self.edges:
                lines.append(f"  - `{edge.source}` → `{edge.target}`")

        return "\n".join(lines)


class ManifestParser:
    """Parse build manifests to determine module structure and dependencies.

    Args:
        repo_root: Absolute path to the repository root.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root.resolve()

    def parse(self) -> ModuleGraph:
        """Detect project type and parse module structure.

        Returns:
            ModuleGraph with discovered modules and dependency edges.
        """
        # Try each parser in order of specificity
        for detector, parser in [
            ("pom.xml", self._parse_maven),
            ("settings.gradle", self._parse_gradle),
            ("settings.gradle.kts", self._parse_gradle),
            ("build.gradle", self._parse_gradle_single),
            ("build.gradle.kts", self._parse_gradle_single),
            ("package.json", self._parse_npm),
            ("go.mod", self._parse_go),
            ("pyproject.toml", self._parse_python),
            ("setup.cfg", self._parse_python_legacy),
            ("setup.py", self._parse_python_legacy),
        ]:
            manifest = self._repo_root / detector
            if manifest.exists():
                try:
                    graph = parser(manifest)
                    if graph.modules:
                        log_message(
                            f"ManifestParser: detected {graph.project_type} "
                            f"with {len(graph.modules)} module(s)"
                        )
                        return graph
                except Exception as exc:
                    log_message(f"ManifestParser: failed to parse {detector}: {exc}")

        return ModuleGraph(project_type="unknown")

    # ------------------------------------------------------------------
    # Maven
    # ------------------------------------------------------------------

    def _parse_maven(self, pom_path: Path) -> ModuleGraph:
        """Parse Maven pom.xml for modules and inter-module dependencies."""
        modules: list[Module] = []
        edges: list[Dependency] = []
        edge_set: set[Dependency] = set()

        try:
            tree = SafeET.parse(pom_path)
        except ET.ParseError as exc:
            raise ET.ParseError(f"Invalid XML in {pom_path.name}: {exc}") from exc
        if tree is None:
            raise ET.ParseError(f"Failed to parse {pom_path.name}")
        root = tree.getroot()
        if root is None:  # pragma: no cover – defensive
            raise ET.ParseError(f"Empty document in {pom_path.name}")
        ns = self._maven_ns(root)

        # Get parent artifact ID
        parent_artifact = self._xml_text(root, f"{ns}artifactId") or "root"
        modules.append(Module(name=parent_artifact, path=".", manifest_file="pom.xml"))

        # Single pass: collect all modules, their artifact IDs, and parsed sub-roots
        sub_pom_data: list[tuple[str, ET.Element, str]] = []  # (artifact_id, sub_root, sub_ns)
        for mod_elem in root.iter(f"{ns}module"):
            if mod_elem.text:
                mod_name = mod_elem.text.strip()
                mod_path = mod_name

                # Try to read the sub-module's pom for its artifactId
                sub_pom = self._repo_root / mod_path / "pom.xml"
                artifact_id = mod_name
                if sub_pom.exists():
                    try:
                        sub_tree = SafeET.parse(sub_pom)
                        if sub_tree is None:
                            raise ET.ParseError(f"Failed to parse {sub_pom}")
                        sub_root = sub_tree.getroot()
                        if sub_root is None:
                            raise ET.ParseError(f"Empty document in {sub_pom}")
                        sub_ns = self._maven_ns(sub_root)
                        artifact_id = self._xml_text(sub_root, f"{sub_ns}artifactId") or mod_name
                        sub_pom_data.append((artifact_id, sub_root, sub_ns))
                    except ET.ParseError as exc:
                        log_message(f"ManifestParser: skipping malformed POM {sub_pom}: {exc}")

                modules.append(Module(name=artifact_id, path=mod_path, manifest_file="pom.xml"))

        # Resolve cross-references now that all modules are known
        all_artifact_ids = {m.name for m in modules}
        for artifact_id, sub_root, sub_ns in sub_pom_data:
            for dep in sub_root.iter(f"{sub_ns}dependency"):
                dep_artifact = self._xml_text(dep, f"{sub_ns}artifactId")
                if (
                    dep_artifact
                    and dep_artifact in all_artifact_ids
                    and dep_artifact != artifact_id
                ):
                    edge = Dependency(source=artifact_id, target=dep_artifact)
                    if edge not in edge_set:
                        edge_set.add(edge)
                        edges.append(edge)

        return ModuleGraph(project_type="maven", modules=modules, edges=edges)

    @staticmethod
    def _maven_ns(root: ET.Element) -> str:
        """Extract Maven namespace prefix from root element."""
        tag = root.tag
        if tag.startswith("{"):
            return tag.split("}")[0] + "}"
        return ""

    @staticmethod
    def _xml_text(parent: ET.Element, tag: str) -> str | None:
        """Get text content of a direct child element."""
        elem = parent.find(tag)
        return elem.text.strip() if elem is not None and elem.text else None

    # ------------------------------------------------------------------
    # Gradle
    # ------------------------------------------------------------------

    def _parse_gradle(self, settings_path: Path) -> ModuleGraph:
        """Parse Gradle settings.gradle for sub-projects."""
        modules: list[Module] = []
        edges: list[Dependency] = []

        content = settings_path.read_text(errors="replace")
        modules.append(Module(name="root", path=".", manifest_file=settings_path.name))

        # Match include directives in both paren and non-paren forms.
        # Paren form handles multiline: include(':a', ':b', ':c')
        include_paren_re = re.compile(r"""include\s*\(([^)]+)\)""", re.DOTALL)
        # Non-paren form (single line): include ':a', ':b'
        include_line_re = re.compile(r"""include\s+([^\n(]+)""")
        module_name_re = re.compile(r"""['"]:([\w.:-]+)['"]""")
        seen_modules: set[str] = set()
        include_matches = list(include_paren_re.finditer(content)) + list(
            include_line_re.finditer(content)
        )
        for include_match in include_matches:
            args_text = include_match.group(1)
            for m in module_name_re.finditer(args_text):
                mod_name = m.group(1)
                if mod_name in seen_modules:
                    continue
                seen_modules.add(mod_name)
                # Gradle convention: colons map to directories
                mod_path = mod_name.replace(":", "/")
                manifest = (
                    "build.gradle.kts" if settings_path.name.endswith(".kts") else "build.gradle"
                )
                modules.append(Module(name=mod_name, path=mod_path, manifest_file=manifest))

        # Parse dependencies from each sub-project's build file
        all_names = {m.name for m in modules}
        edge_set: set[Dependency] = set()
        for mod in modules:
            if mod.path == ".":
                continue
            for build_file in ["build.gradle.kts", "build.gradle"]:
                build_path = self._repo_root / mod.path / build_file
                if build_path.exists():
                    self._parse_gradle_deps(build_path, mod.name, all_names, edges, edge_set)
                    break

        return ModuleGraph(project_type="gradle", modules=modules, edges=edges)

    def _parse_gradle_single(self, build_path: Path) -> ModuleGraph:
        """Parse single-module Gradle project."""
        name = self._repo_root.name
        modules = [Module(name=name, path=".", manifest_file=build_path.name)]
        return ModuleGraph(project_type="gradle", modules=modules)

    @staticmethod
    def _parse_gradle_deps(
        build_path: Path,
        module_name: str,
        all_names: set[str],
        edges: list[Dependency],
        edge_set: set[Dependency] | None = None,
    ) -> None:
        """Extract inter-project dependency references from a Gradle build file."""
        if edge_set is None:
            edge_set = set(edges)
        content = build_path.read_text(errors="replace")
        # Match project(':module-name') dependencies
        project_dep_re = re.compile(r"""project\s*\(\s*['"]:([\w.:-]+)['"]\s*\)""")
        for m in project_dep_re.finditer(content):
            dep_name = m.group(1)
            if dep_name in all_names:
                edge = Dependency(source=module_name, target=dep_name)
                if edge not in edge_set:
                    edge_set.add(edge)
                    edges.append(edge)

    # ------------------------------------------------------------------
    # npm / Node.js
    # ------------------------------------------------------------------

    def _parse_npm(self, package_path: Path) -> ModuleGraph:
        """Parse npm package.json for workspaces."""

        modules: list[Module] = []

        content = package_path.read_text(errors="replace")
        data = json.loads(content)

        root_name = data.get("name", self._repo_root.name)
        modules.append(Module(name=root_name, path=".", manifest_file="package.json"))

        # Parse workspaces
        workspaces = data.get("workspaces", [])
        if isinstance(workspaces, dict):
            # Yarn workspaces format: { "packages": [...] }
            workspaces = workspaces.get("packages", [])

        if isinstance(workspaces, list):
            for ws_glob in workspaces:
                # Resolve workspace globs
                ws_glob = ws_glob.rstrip("/")
                if "*" in ws_glob:
                    # e.g., "packages/*"
                    base_dir = ws_glob.split("*")[0].rstrip("/")
                    base_path = self._repo_root / base_dir
                    if base_path.is_dir():
                        for sub in sorted(base_path.iterdir()):
                            pkg_json = sub / "package.json"
                            if pkg_json.exists():
                                try:
                                    pkg_data = json.loads(pkg_json.read_text(errors="replace"))
                                    pkg_name = pkg_data.get("name", sub.name)
                                except json.JSONDecodeError:
                                    pkg_name = sub.name
                                rel = str(sub.relative_to(self._repo_root))
                                modules.append(
                                    Module(name=pkg_name, path=rel, manifest_file="package.json")
                                )
                else:
                    # Exact workspace path
                    ws_path = self._repo_root / ws_glob
                    pkg_json = ws_path / "package.json"
                    if pkg_json.exists():
                        try:
                            pkg_data = json.loads(pkg_json.read_text(errors="replace"))
                            pkg_name = pkg_data.get("name", ws_path.name)
                        except json.JSONDecodeError:
                            pkg_name = ws_path.name
                        modules.append(
                            Module(name=pkg_name, path=ws_glob, manifest_file="package.json")
                        )

        return ModuleGraph(project_type="npm", modules=modules)

    # ------------------------------------------------------------------
    # Go
    # ------------------------------------------------------------------

    def _parse_go(self, go_mod_path: Path) -> ModuleGraph:
        """Parse go.mod for module path."""
        content = go_mod_path.read_text(errors="replace")

        module_name = "unknown"
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("module "):
                module_name = line.split(None, 1)[1].strip()
                break

        modules = [Module(name=module_name, path=".", manifest_file="go.mod")]
        return ModuleGraph(project_type="go", modules=modules)

    # ------------------------------------------------------------------
    # Python
    # ------------------------------------------------------------------

    def _parse_python(self, pyproject_path: Path) -> ModuleGraph:
        """Parse pyproject.toml for Python project structure."""
        name = self._repo_root.name
        try:
            raw = pyproject_path.read_bytes()
            data = tomllib.loads(raw.decode("utf-8"))
            name = data.get("project", {}).get("name", name)
        except (tomllib.TOMLDecodeError, ValueError, KeyError, UnicodeDecodeError):
            # Fall back to regex extraction on TOML parse/access errors
            content = pyproject_path.read_text(errors="replace")
            name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.MULTILINE)
            if name_match:
                name = name_match.group(1)

        modules = [Module(name=name, path=".", manifest_file="pyproject.toml")]
        return ModuleGraph(project_type="python", modules=modules)

    def _parse_python_legacy(self, setup_path: Path) -> ModuleGraph:
        """Parse setup.cfg or setup.py for Python project structure."""
        content = setup_path.read_text(errors="replace")

        name = self._repo_root.name
        # setup.cfg: name = foo
        name_match = re.search(r"^\s*name\s*=\s*(.+)$", content, re.MULTILINE)
        if name_match:
            name = name_match.group(1).split("#")[0].strip()

        modules = [Module(name=name, path=".", manifest_file=setup_path.name)]
        return ModuleGraph(project_type="python", modules=modules)


__all__ = ["Dependency", "ManifestParser", "Module", "ModuleGraph"]
