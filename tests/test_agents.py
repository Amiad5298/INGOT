"""Tests for ingot.integrations.agents module."""

import pytest

from ingot.integrations.agent_templates import load_template
from ingot.integrations.agents import (
    _REQUIRED_AGENTS,
    AGENT_BODIES,
    AGENT_METADATA,
    apply_model_overrides,
    get_agents_dir,
    parse_agent_frontmatter,
    verify_agents_available,
)
from ingot.workflow.constants import (
    INGOT_AGENT_IMPLEMENTER,
    INGOT_AGENT_PLANNER,
    INGOT_AGENT_RESEARCHER,
    INGOT_AGENT_REVIEWER,
    INGOT_AGENT_TASKLIST,
    INGOT_AGENT_TASKLIST_REFINER,
    RESEARCHER_SECTION_HEADINGS,
)


class TestVerifyAgentsAvailable:
    """Only required agents from AGENT_METADATA are checked."""

    def test_only_required_agents_checked_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # No agents dir — only required agents should be missing
        all_ok, missing = verify_agents_available()
        assert not all_ok
        expected_names = {
            meta["name"] for key, meta in AGENT_METADATA.items() if key in _REQUIRED_AGENTS
        }
        assert set(missing) == expected_names

    def test_optional_agents_not_reported(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        all_ok, missing = verify_agents_available()
        # Optional agents should NOT appear in missing list
        assert "ingot-reviewer" not in missing
        assert "ingot-researcher" not in missing
        assert "ingot-tasklist-refiner" not in missing

    def test_all_required_present_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True, exist_ok=True)
        # Only create required agents
        for key, meta in AGENT_METADATA.items():
            if key in _REQUIRED_AGENTS:
                (agents_dir / f"{meta['name']}.md").write_text("# agent")

        all_ok, missing = verify_agents_available()
        assert all_ok
        assert missing == []


class TestResearcherSectionHeadingsSync:
    """Assert all RESEARCHER_SECTION_HEADINGS appear in researcher prompt body."""

    def test_all_headings_in_researcher_body(self):
        researcher_body = AGENT_BODIES[INGOT_AGENT_RESEARCHER]
        for heading in RESEARCHER_SECTION_HEADINGS:
            # Strip the leading "### " to match the heading text in the prompt
            heading_text = heading.lstrip("# ")
            assert (
                heading_text in researcher_body
            ), f"Heading '{heading}' not found in researcher prompt body"


class TestTemplateLoading:
    """Verify all agent prompts are loaded from template files."""

    @pytest.mark.parametrize(
        "agent_key,template_name",
        [
            (INGOT_AGENT_RESEARCHER, "researcher"),
            (INGOT_AGENT_PLANNER, "planner"),
            (INGOT_AGENT_TASKLIST, "tasklist"),
            (INGOT_AGENT_TASKLIST_REFINER, "tasklist_refiner"),
            (INGOT_AGENT_IMPLEMENTER, "implementer"),
            (INGOT_AGENT_REVIEWER, "reviewer"),
        ],
    )
    def test_agent_body_matches_template(self, agent_key, template_name):
        body = AGENT_BODIES[agent_key]
        template = load_template(template_name)
        assert body == template

    @pytest.mark.parametrize(
        "template_name,expected_marker",
        [
            ("researcher", "## Research Rules"),
            ("planner", "## HARD GATES"),
            ("tasklist", "## GATE 1"),
            ("tasklist_refiner", "# Your Single Job"),
            ("implementer", "Phase 1: Orient"),
            ("reviewer", "PASS"),
        ],
    )
    def test_template_contains_expected_marker(self, template_name, expected_marker):
        body = load_template(template_name)
        assert expected_marker in body

    def test_implementer_body_contains_three_phases(self):
        body = AGENT_BODIES[INGOT_AGENT_IMPLEMENTER]
        assert "Phase 1: Orient" in body
        assert "Phase 2: Implement Incrementally" in body
        assert "Phase 3: Verify Before Completing" in body

    def test_implementer_body_has_no_test_writing_instruction(self):
        body = AGENT_BODIES[INGOT_AGENT_IMPLEMENTER]
        assert "Write tests alongside" not in body


SAMPLE_AGENT_CONTENT = """\
---
name: ingot-planner
description: INGOT workflow planner
model: claude-sonnet-4-5
color: blue
ingot_version: 1.0.0
ingot_content_hash: abc123
---

You are a planner agent.
"""


class TestApplyModelOverrides:
    """Tests for apply_model_overrides()."""

    def test_patches_model_in_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        (agents_dir / "ingot-planner.md").write_text(SAMPLE_AGENT_CONTENT)

        apply_model_overrides({"ingot-planner": "claude-opus-4-5"})

        updated = (agents_dir / "ingot-planner.md").read_text()
        fm = parse_agent_frontmatter(updated)
        assert fm["model"] == "claude-opus-4-5"

    def test_skips_when_model_already_correct(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        (agents_dir / "ingot-planner.md").write_text(SAMPLE_AGENT_CONTENT)

        apply_model_overrides({"ingot-planner": "claude-sonnet-4-5"})

        # Content should be unchanged (model already matches)
        updated = (agents_dir / "ingot-planner.md").read_text()
        assert updated == SAMPLE_AGENT_CONTENT

    def test_skips_missing_agent_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        # No agent file created — should not raise
        apply_model_overrides({"ingot-planner": "claude-opus-4-5"})

    def test_skips_file_without_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        content = "You are a plain agent without frontmatter."
        (agents_dir / "ingot-planner.md").write_text(content)

        apply_model_overrides({"ingot-planner": "claude-opus-4-5"})

        # Content should be unchanged
        assert (agents_dir / "ingot-planner.md").read_text() == content

    def test_noop_with_empty_overrides(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        (agents_dir / "ingot-planner.md").write_text(SAMPLE_AGENT_CONTENT)

        apply_model_overrides({})

        # Content should be unchanged
        assert (agents_dir / "ingot-planner.md").read_text() == SAMPLE_AGENT_CONTENT

    def test_patches_multiple_agents(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)

        planner_content = SAMPLE_AGENT_CONTENT
        impl_content = SAMPLE_AGENT_CONTENT.replace("ingot-planner", "ingot-implementer").replace(
            "planner", "implementer"
        )
        (agents_dir / "ingot-planner.md").write_text(planner_content)
        (agents_dir / "ingot-implementer.md").write_text(impl_content)

        apply_model_overrides(
            {
                "ingot-planner": "claude-opus-4-5",
                "ingot-implementer": "claude-haiku-3-5",
            }
        )

        planner_fm = parse_agent_frontmatter((agents_dir / "ingot-planner.md").read_text())
        impl_fm = parse_agent_frontmatter((agents_dir / "ingot-implementer.md").read_text())
        assert planner_fm["model"] == "claude-opus-4-5"
        assert impl_fm["model"] == "claude-haiku-3-5"

    def test_preserves_other_frontmatter_fields(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        agents_dir = get_agents_dir()
        agents_dir.mkdir(parents=True)
        (agents_dir / "ingot-planner.md").write_text(SAMPLE_AGENT_CONTENT)

        apply_model_overrides({"ingot-planner": "claude-opus-4-5"})

        fm = parse_agent_frontmatter((agents_dir / "ingot-planner.md").read_text())
        assert fm["name"] == "ingot-planner"
        assert fm["color"] == "blue"
        assert fm["ingot_version"] == "1.0.0"
        assert fm["ingot_content_hash"] == "abc123"
