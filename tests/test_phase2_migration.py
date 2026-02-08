"""Tests for Phase 2 (AMI-67) workflow refactoring.

Covers:
- WorkflowState new fields (backend_model, backend_name, fixer subagent)
- Runner populates backend metadata from injected backend
- All workflow modules use run_with_callback (not run_print_with_output)
- BackendFactory creates fresh instances per call
- SPECFLOW_AGENT_FIXER constant and subagent naming
"""

import ast
from pathlib import Path

import pytest

from spec.config.fetch_config import AgentPlatform
from spec.config.settings import Settings
from spec.integrations.backends.factory import BackendFactory
from spec.integrations.providers import GenericTicket, Platform
from spec.workflow.constants import (
    SPECFLOW_AGENT_DOC_UPDATER,
    SPECFLOW_AGENT_FIXER,
    SPECFLOW_AGENT_IMPLEMENTER,
    SPECFLOW_AGENT_PLANNER,
    SPECFLOW_AGENT_REVIEWER,
    SPECFLOW_AGENT_TASKLIST,
    SPECFLOW_AGENT_TASKLIST_REFINER,
)
from spec.workflow.state import WorkflowState

# =============================================================================
# WorkflowState new fields (AMI-68)
# =============================================================================


class TestWorkflowStateBackendFields:
    """Tests for backend metadata fields on WorkflowState."""

    def test_backend_model_defaults_to_none(self):
        """backend_model defaults to None."""
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_model is None

    def test_backend_name_defaults_to_none(self):
        """backend_name defaults to None."""
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_name is None

    def test_backend_platform_defaults_to_none(self):
        """backend_platform defaults to None."""
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.backend_platform is None

    def test_backend_fields_can_be_set(self):
        """Backend metadata fields can be set at construction."""
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


# =============================================================================
# Subagent naming: SPECFLOW_AGENT_FIXER (AMI-75)
# =============================================================================


class TestSubagentFixer:
    """Tests for SPECFLOW_AGENT_FIXER constant and subagent naming."""

    def test_fixer_constant_exists(self):
        """SPECFLOW_AGENT_FIXER is exported from constants."""
        assert SPECFLOW_AGENT_FIXER is not None

    def test_fixer_reuses_implementer(self):
        """Fixer reuses the implementer agent name."""
        assert SPECFLOW_AGENT_FIXER == SPECFLOW_AGENT_IMPLEMENTER

    def test_fixer_in_workflow_state_defaults(self):
        """WorkflowState subagent_names includes 'fixer' key."""
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert "fixer" in state.subagent_names
        assert state.subagent_names["fixer"] == SPECFLOW_AGENT_FIXER

    def test_all_subagent_keys_present(self):
        """WorkflowState subagent_names contains all expected keys."""
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
        """Settings dataclass has subagent_fixer field."""
        settings = Settings()
        assert hasattr(settings, "subagent_fixer")
        assert settings.subagent_fixer == "spec-implementer"

    def test_settings_key_mapping_includes_fixer(self):
        """Settings key mapping includes SUBAGENT_FIXER."""
        settings = Settings()
        assert settings.get_attribute_for_key("SUBAGENT_FIXER") == "subagent_fixer"


# =============================================================================
# BackendFactory creates fresh instances (AMI-73)
# =============================================================================


class TestBackendFactoryFreshInstances:
    """Tests verifying BackendFactory creates independent instances."""

    def test_factory_creates_new_instance_each_call(self):
        """Each BackendFactory.create() call returns a new instance."""
        backend1 = BackendFactory.create(AgentPlatform.AUGGIE)
        backend2 = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend1 is not backend2

    def test_factory_passes_model_to_backend(self):
        """BackendFactory.create() passes model parameter."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE, model="test-model")
        assert backend.model == "test-model"

    def test_factory_default_model_is_empty(self):
        """BackendFactory.create() defaults to empty model."""
        backend = BackendFactory.create(AgentPlatform.AUGGIE)
        assert backend.model == ""


# =============================================================================
# No run_print_with_output in workflow layer (AMI-72, AMI-75)
# =============================================================================


class TestNoRunPrintWithOutputInWorkflow:
    """Verify workflow modules don't call run_print_with_output.

    After Phase 2 migration, all workflow code should use run_with_callback().
    run_print_with_output() should only exist in backend implementations.
    """

    WORKFLOW_MODULES = [
        "spec/workflow/autofix.py",
        "spec/workflow/review.py",
        "spec/workflow/step1_plan.py",
        "spec/workflow/step2_tasklist.py",
        "spec/workflow/step3_execute.py",
        "spec/workflow/step4_update_docs.py",
        "spec/workflow/runner.py",
        "spec/workflow/conflict_detection.py",
    ]

    @pytest.mark.parametrize("module_path", WORKFLOW_MODULES)
    def test_workflow_module_uses_run_with_callback(self, module_path):
        """Workflow module does not call backend.run_print_with_output()."""
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


# =============================================================================
# Runner populates backend metadata (AMI-68)
# =============================================================================


class TestRunnerBackendMetadata:
    """Tests verifying runner passes backend metadata to WorkflowState."""

    def test_runner_source_populates_backend_model(self):
        """Runner source code sets backend_model on WorkflowState."""
        runner_path = Path(__file__).parent.parent / "spec/workflow/runner.py"
        source = runner_path.read_text()
        assert "backend_model=" in source, "runner.py should set backend_model on WorkflowState"

    def test_runner_source_populates_backend_name(self):
        """Runner source code sets backend_name on WorkflowState."""
        runner_path = Path(__file__).parent.parent / "spec/workflow/runner.py"
        source = runner_path.read_text()
        assert "backend_name=" in source, "runner.py should set backend_name on WorkflowState"

    def test_runner_source_populates_fixer_subagent(self):
        """Runner source code includes 'fixer' in subagent_names dict."""
        runner_path = Path(__file__).parent.parent / "spec/workflow/runner.py"
        source = runner_path.read_text()
        assert '"fixer"' in source, "runner.py should include 'fixer' key in subagent_names"


# =============================================================================
# Autofix uses fixer subagent (AMI-75)
# =============================================================================


class TestAutofixUsesFixer:
    """Tests verifying autofix.py uses the fixer subagent key."""

    def test_autofix_source_references_fixer(self):
        """autofix.py uses subagent_names['fixer'] or .get('fixer', ...)."""
        autofix_path = Path(__file__).parent.parent / "spec/workflow/autofix.py"
        source = autofix_path.read_text()
        assert "fixer" in source, "autofix.py should reference 'fixer' subagent key"

    def test_autofix_uses_run_with_callback(self):
        """autofix.py uses run_with_callback, not run_print_with_output."""
        autofix_path = Path(__file__).parent.parent / "spec/workflow/autofix.py"
        source = autofix_path.read_text()
        assert "run_with_callback" in source
        assert "run_print_with_output" not in source


# =============================================================================
# Constants consistency (AMI-68 / AMI-75)
# =============================================================================


class TestConstantsConsistency:
    """Tests verifying constants are consistent across modules."""

    def test_constants_match_settings_defaults(self):
        """Settings defaults match workflow constants."""
        settings = Settings()
        assert settings.subagent_planner == SPECFLOW_AGENT_PLANNER
        assert settings.subagent_tasklist == SPECFLOW_AGENT_TASKLIST
        assert settings.subagent_tasklist_refiner == SPECFLOW_AGENT_TASKLIST_REFINER
        assert settings.subagent_implementer == SPECFLOW_AGENT_IMPLEMENTER
        assert settings.subagent_reviewer == SPECFLOW_AGENT_REVIEWER
        assert settings.subagent_fixer == SPECFLOW_AGENT_FIXER
        assert settings.subagent_doc_updater == SPECFLOW_AGENT_DOC_UPDATER

    def test_workflow_state_defaults_match_constants(self):
        """WorkflowState subagent_names defaults match constants."""
        ticket = GenericTicket(id="T-1", platform=Platform.JIRA, url="", title="", description="")
        state = WorkflowState(ticket=ticket)
        assert state.subagent_names["planner"] == SPECFLOW_AGENT_PLANNER
        assert state.subagent_names["tasklist"] == SPECFLOW_AGENT_TASKLIST
        assert state.subagent_names["tasklist_refiner"] == SPECFLOW_AGENT_TASKLIST_REFINER
        assert state.subagent_names["implementer"] == SPECFLOW_AGENT_IMPLEMENTER
        assert state.subagent_names["reviewer"] == SPECFLOW_AGENT_REVIEWER
        assert state.subagent_names["fixer"] == SPECFLOW_AGENT_FIXER
        assert state.subagent_names["doc_updater"] == SPECFLOW_AGENT_DOC_UPDATER
