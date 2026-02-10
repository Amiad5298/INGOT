"""Tests for Phase 2 (AMI-67) workflow refactoring.

Covers:
- WorkflowState new fields (backend_model, backend_name, fixer subagent)
- Runner populates backend metadata from injected backend
- All workflow modules use run_with_callback (not run_print_with_output)
- BackendFactory creates fresh instances per call
- INGOT_AGENT_FIXER constant and subagent naming
"""

import ast
from pathlib import Path

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.config.settings import Settings
from ingot.integrations.backends.factory import BackendFactory
from ingot.integrations.providers import GenericTicket, Platform
from ingot.workflow.constants import (
    INGOT_AGENT_DOC_UPDATER,
    INGOT_AGENT_FIXER,
    INGOT_AGENT_IMPLEMENTER,
    INGOT_AGENT_PLANNER,
    INGOT_AGENT_REVIEWER,
    INGOT_AGENT_TASKLIST,
    INGOT_AGENT_TASKLIST_REFINER,
)
from ingot.workflow.state import WorkflowState


class TestWorkflowStateBackendFields:
    def test_backend_model_defaults_to_none(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_model is None

    def test_backend_name_defaults_to_none(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_name is None

    def test_backend_platform_defaults_to_none(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_platform is None

    def test_backend_fields_can_be_set(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(
            ticket=ticket,
            backend_platform=AgentPlatform.AUGGIE,
            backend_model="claude-3",
            backend_name="Auggie",
        )
        assert state.backend_platform == AgentPlatform.AUGGIE
        assert state.backend_model == "claude-3"
        assert state.backend_name == "Auggie"


class TestSubagentFixer:
    def test_fixer_constant_exists(self):
        assert INGOT_AGENT_FIXER is not None

    def test_fixer_reuses_implementer(self):
        assert INGOT_AGENT_FIXER == INGOT_AGENT_IMPLEMENTER

    def test_fixer_in_workflow_state_defaults(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert "fixer" in state.subagent_names
        assert state.subagent_names["fixer"] == INGOT_AGENT_FIXER

    def test_all_subagent_keys_present(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        expected_keys = {
            "planner",
            "tasklist",
            "tasklist_refiner",
            "implementer",
            "reviewer",
            "fixer",
            "doc_updater",
        }
        assert set(state.subagent_names.keys()) == expected_keys

    def test_settings_has_subagent_fixer(self):
        settings = Settings()
        assert hasattr(settings, "subagent_fixer")
        assert settings.subagent_fixer == "ingot-implementer"

    def test_settings_key_mapping_includes_fixer(self):
        settings = Settings()
        assert settings.get_attribute_for_key("SUBAGENT_FIXER") == "subagent_fixer"


class TestBackendFactoryFreshInstances:
    def test_factory_creates_new_instance_each_call(self):
        backend1 = BackendFactory.create(AgentPlatform.AUGGIE)
        backend2 = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend1 is not backend2

    def test_factory_passes_model_to_backend(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="test-model")
        assert backend.model == "test-model"

    def test_factory_default_model_is_empty(self):
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.model == ""


class TestNoRunPrintWithOutputInWorkflow:
    """Verify workflow modules don't call run_print_with_output.

    After Phase 2 migration, all workflow code should use run_with_callback().
    run_print_with_output() should only exist in backend implementations.
    """

    WORKFLOW_MODULES = [
        "ingot/workflow/autofix.py",
        "ingot/workflow/review.py",
        "ingot/workflow/step1_plan.py",
        "ingot/workflow/step2_tasklist.py",
        "ingot/workflow/step3_execute.py",
        "ingot/workflow/step4_update_docs.py",
        "ingot/workflow/runner.py",
        "ingot/workflow/conflict_detection.py",
    ]

    @pytest.mark.parametrize("module_path", WORKFLOW_MODULES)
    def test_workflow_module_uses_run_with_callback(self, module_path):
        full_path = Path(__file__).parent.parent / module_path
        if not full_path.exists():
            pytest.skip(f"{module_path} not found")

        source = full_path.read_text()
        # Parse AST and look for attribute access on 'run_print_with_output'
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "run_print_with_output":
                # Check if this is a method call (not just a reference in comments)
                pytest.fail(
                    f"{module_path} still calls run_print_with_output "
                    f"at line {node.lineno}. Should use run_with_callback()."
                )


class TestRunnerBackendMetadata:
    def test_runner_source_populates_backend_model(self):
        runner_path = Path(__file__).parent.parent / "ingot/workflow/runner.py"
        source = runner_path.read_text()
        assert "backend_model=" in source, "runner.py should set backend_model on WorkflowState"

    def test_runner_source_populates_backend_name(self):
        runner_path = Path(__file__).parent.parent / "ingot/workflow/runner.py"
        source = runner_path.read_text()
        assert "backend_name=" in source, "runner.py should set backend_name on WorkflowState"

    def test_runner_source_populates_fixer_subagent(self):
        runner_path = Path(__file__).parent.parent / "ingot/workflow/runner.py"
        source = runner_path.read_text()
        assert '"fixer"' in source, "runner.py should include 'fixer' key in subagent_names"


class TestAutofixUsesFixer:
    def test_autofix_source_references_fixer(self):
        autofix_path = Path(__file__).parent.parent / "ingot/workflow/autofix.py"
        source = autofix_path.read_text()
        assert "fixer" in source, "autofix.py should reference 'fixer' subagent key"

    def test_autofix_uses_run_with_callback(self):
        autofix_path = Path(__file__).parent.parent / "ingot/workflow/autofix.py"
        source = autofix_path.read_text()
        assert "run_with_callback" in source
        assert "run_print_with_output" not in source


class TestConstantsConsistency:
    def test_constants_match_settings_defaults(self):
        settings = Settings()
        assert settings.subagent_planner == INGOT_AGENT_PLANNER
        assert settings.subagent_tasklist == INGOT_AGENT_TASKLIST
        assert settings.subagent_tasklist_refiner == INGOT_AGENT_TASKLIST_REFINER
        assert settings.subagent_implementer == INGOT_AGENT_IMPLEMENTER
        assert settings.subagent_reviewer == INGOT_AGENT_REVIEWER
        assert settings.subagent_fixer == INGOT_AGENT_FIXER
        assert settings.subagent_doc_updater == INGOT_AGENT_DOC_UPDATER

    def test_workflow_state_defaults_match_constants(self):
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.subagent_names["planner"] == INGOT_AGENT_PLANNER
        assert state.subagent_names["tasklist"] == INGOT_AGENT_TASKLIST
        assert state.subagent_names["tasklist_refiner"] == INGOT_AGENT_TASKLIST_REFINER
        assert state.subagent_names["implementer"] == INGOT_AGENT_IMPLEMENTER
        assert state.subagent_names["reviewer"] == INGOT_AGENT_REVIEWER
        assert state.subagent_names["fixer"] == INGOT_AGENT_FIXER
        assert state.subagent_names["doc_updater"] == INGOT_AGENT_DOC_UPDATER
