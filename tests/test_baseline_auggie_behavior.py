"""Baseline behavior tests for Auggie workflow.

These tests capture the current behavior of AuggieClient and workflow steps
BEFORE the multi-backend refactoring. They serve as regression tests to ensure
the new AIBackend abstraction maintains identical semantics.

Run with: INGOT_INTEGRATION_TESTS=1 pytest tests/test_baseline_auggie_behavior.py -v

IMPORTANT: All tests in this file must pass with the current codebase
before proceeding to Phase 1 of the multi-backend refactoring.
"""

import inspect
import os
import subprocess

import pytest

# Marker for tests that require running the Auggie CLI (integration/CLI tests)
requires_integration = pytest.mark.skipif(
    os.environ.get("INGOT_INTEGRATION_TESTS") != "1",
    reason="Integration tests require INGOT_INTEGRATION_TESTS=1",
)


class TestImportability:
    """Verify that required functions and classes are importable.

    These tests ensure that the baseline tests can actually import
    the functions they need to test. This catches issues where
    private functions are not accessible.
    """

    def testlooks_like_rate_limit_is_importable(self):
        try:
            from ingot.integrations.auggie import looks_like_rate_limit

            assert callable(looks_like_rate_limit), "Must be callable"
        except ImportError as e:
            pytest.fail(
                f"Cannot import looks_like_rate_limit: {e}\n"
                "This function is required for rate limit detection tests."
            )

    def test_auggie_client_is_importable(self):
        try:
            from ingot.integrations.auggie import AuggieClient

            assert AuggieClient is not None
        except ImportError as e:
            pytest.fail(f"Cannot import AuggieClient: {e}")

    def test_ingot_agent_constants_are_importable(self):
        try:
            from ingot.workflow.constants import (
                INGOT_AGENT_DOC_UPDATER,
                INGOT_AGENT_IMPLEMENTER,
                INGOT_AGENT_PLANNER,
                INGOT_AGENT_REVIEWER,
                INGOT_AGENT_TASKLIST,
                INGOT_AGENT_TASKLIST_REFINER,
            )

            # Verify they are strings
            for const in [
                INGOT_AGENT_PLANNER,
                INGOT_AGENT_TASKLIST,
                INGOT_AGENT_TASKLIST_REFINER,
                INGOT_AGENT_IMPLEMENTER,
                INGOT_AGENT_REVIEWER,
                INGOT_AGENT_DOC_UPDATER,
            ]:
                assert isinstance(const, str), f"Constant must be str: {const}"
        except ImportError as e:
            pytest.fail(f"Cannot import INGOT_AGENT_* constants: {e}")


@requires_integration
class TestAuggieClientSemantics:
    """Capture current AuggieClient method semantics.

    These tests verify the EXACT return types and behaviors of AuggieClient
    methods. Any new backend implementation MUST match these semantics.

    NOTE: These tests require the Auggie CLI and are skipped unless
    INGOT_INTEGRATION_TESTS=1 is set.
    """

    def test_run_with_callback_returns_tuple_bool_str(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        output_lines = []

        success, output = client.run_with_callback(
            "Say exactly: BASELINE_TEST_OK",
            output_callback=output_lines.append,
            dont_save_session=True,
        )

        # Verify return type semantics
        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"
        # Verify callback was called (only assert if success, as failures may have no output)
        if success:
            assert len(output_lines) > 0, "Callback should receive output lines on success"

    def test_run_with_callback_tuple_length_is_two(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        result = client.run_with_callback(
            "Say exactly: BASELINE_TEST_OK",
            output_callback=lambda _: None,
            dont_save_session=True,
        )

        assert isinstance(result, tuple), "Return value must be a tuple"
        assert len(result) == 2, "Tuple must have exactly two elements"

    def test_run_print_with_output_returns_tuple_bool_str(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        success, output = client.run_print_with_output(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"

    def test_run_print_quiet_returns_str(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        output = client.run_print_quiet(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(output, str), "Must return str"

    def test_run_print_returns_bool(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        success = client.run_print(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(success, bool), "Must return bool"

    def test_run_returns_completed_process(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        result = client.run(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(result, subprocess.CompletedProcess), "Must return CompletedProcess"
        assert isinstance(result.returncode, int), "returncode must be int"

    def test_callback_receives_lines_without_newlines(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        callback_lines = []

        success, output = client.run_with_callback(
            "Say exactly on two lines:\nLine 1\nLine 2",
            output_callback=callback_lines.append,
            dont_save_session=True,
        )

        # Callback lines should not have trailing newlines
        for line in callback_lines:
            assert not line.endswith("\n"), f"Line should not end with newline: {repr(line)}"

    def test_output_aggregation_preserves_newlines(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        callback_lines = []

        success, output = client.run_with_callback(
            "Say exactly on separate lines: AAA then BBB then CCC",
            output_callback=callback_lines.append,
            dont_save_session=True,
        )

        # Output should contain newlines (multi-line response)
        if len(callback_lines) > 1:
            assert (
                "\n" in output or len(output.splitlines()) > 1
            ), "Multi-line output should preserve newlines in return value"

        # Verify callback lines don't have newlines but output does
        for line in callback_lines:
            assert not line.endswith("\n"), "Callback lines should be stripped"

    def test_run_with_callback_failure_returns_false(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()

        # Use run_argv_with_callback to pass raw CLI args (not a prompt)
        # This guarantees CLI-level failure regardless of LLM/network state
        success, output = client.run_argv_with_callback(
            ["--invalid-flag-xyz"],
            output_callback=lambda x: None,
        )

        # Verify return type semantics (stable contract)
        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"
        # An invalid flag passed as argv reliably fails at CLI level
        assert success is False, "Invalid CLI flag must return success=False"


class TestRateLimitDetection:
    """Capture current rate limit detection behavior.

    These are UNIT TESTS that don't require the Auggie CLI.
    They document the exact patterns that looks_like_rate_limit() matches.
    """

    def testlooks_like_rate_limit_http_429(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("Error 429: Too many requests")
        assert looks_like_rate_limit("HTTP/1.1 429")
        assert looks_like_rate_limit("Status: 429")

    def testlooks_like_rate_limit_explicit_messages(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        rate_limit_outputs = [
            "rate limit exceeded",
            "Rate limit hit, please wait",
            "rate_limit_error",
            "You have exceeded your rate limit",
        ]
        for output in rate_limit_outputs:
            assert looks_like_rate_limit(output), f"Should detect: {output}"

    def testlooks_like_rate_limit_quota_messages(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("quota exceeded for today")
        assert looks_like_rate_limit("Monthly quota exceeded")
        # Note: "API quota reached" does NOT match because pattern is "quota exceeded"
        assert not looks_like_rate_limit("API quota reached")

    def testlooks_like_rate_limit_capacity_messages(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("System at capacity")
        assert looks_like_rate_limit("Capacity limit reached")

    def testlooks_like_rate_limit_throttle_variants(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("Request throttled")
        assert looks_like_rate_limit("Throttling in effect")
        assert looks_like_rate_limit("You are being throttled")

    def testlooks_like_rate_limit_server_errors(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("502 Bad Gateway")
        assert looks_like_rate_limit("503 Service Unavailable")
        assert looks_like_rate_limit("504 Gateway Timeout")

    def testlooks_like_rate_limit_normal_success(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        normal_outputs = [
            "Task completed successfully",
            "File created: test.py",
            "Running tests...",
            "All tests passed",
            "Build successful",
            "Changes committed",
        ]
        for output in normal_outputs:
            assert not looks_like_rate_limit(output), f"Should NOT detect: {output}"

    def test_looks_like_rate_limit_fixed_false_positives(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        # Fixed: 502/503 are no longer detected as rate limits
        fixed_false_positives = [
            "Expected 503 but got 200",  # 503 not a rate limit
            "Test case 502 failed",  # 502 not a rate limit
        ]
        for output in fixed_false_positives:
            assert not looks_like_rate_limit(output), f"Should NOT detect as rate limit: '{output}'"

        # Fixed: embedded status codes no longer match
        assert not looks_like_rate_limit("Working on PROJ-4290")

        # Known limitation: standalone "429" in non-HTTP context still matches
        # because word-boundary regex cannot distinguish context
        assert looks_like_rate_limit("Error on line 429 of main.py")

    def testlooks_like_rate_limit_true_negatives(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        # These should NOT be detected (no rate-limit patterns)
        true_negatives = [
            "Error on line 100 of main.py",
            "Expected 200 but got 404",
            "Test case 42 failed",
            "Connection refused",
            "File not found",
            "Permission denied",
        ]
        for output in true_negatives:
            assert not looks_like_rate_limit(output), f"Should NOT detect: {output}"

    def testlooks_like_rate_limit_case_insensitive(self):
        from ingot.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("RATE LIMIT EXCEEDED")
        assert looks_like_rate_limit("Rate Limit")
        assert looks_like_rate_limit("QUOTA EXCEEDED")


class TestWorkflowStepBehavior:
    """Capture current workflow step behavior patterns.

    These tests verify that subagent names are correctly configured
    in WorkflowState. The multi-backend refactoring must preserve
    these exact names.
    """

    @pytest.fixture
    def mock_state(self):
        """Create a minimal WorkflowState for testing."""
        from ingot.integrations.providers import GenericTicket, Platform
        from ingot.workflow.state import WorkflowState

        ticket = GenericTicket(
            id="TEST-123",
            platform=Platform.GITHUB,
            url="https://example.invalid/TEST-123",
            title="Test ticket for baseline behavior tests",
            description="This ticket is used for baseline testing",
        )

        state = WorkflowState(ticket=ticket)
        return state

    def test_step1_uses_spec_planner_subagent(self, mock_state):
        assert mock_state.subagent_names["planner"] == "ingot-planner"

    def test_step2_uses_spec_tasklist_subagent(self, mock_state):
        assert mock_state.subagent_names["tasklist"] == "ingot-tasklist"

    def test_step2_refiner_uses_spec_tasklist_refiner(self, mock_state):
        assert mock_state.subagent_names["tasklist_refiner"] == "ingot-tasklist-refiner"

    def test_step3_uses_spec_implementer_subagent(self, mock_state):
        assert mock_state.subagent_names["implementer"] == "ingot-implementer"

    def test_step3_uses_spec_reviewer_subagent(self, mock_state):
        assert mock_state.subagent_names["reviewer"] == "ingot-reviewer"

    def test_step4_uses_spec_doc_updater_subagent(self, mock_state):
        assert mock_state.subagent_names["doc_updater"] == "ingot-doc-updater"

    def test_subagent_names_match_constants(self, mock_state):
        from ingot.workflow.constants import (
            INGOT_AGENT_DOC_UPDATER,
            INGOT_AGENT_IMPLEMENTER,
            INGOT_AGENT_PLANNER,
            INGOT_AGENT_REVIEWER,
            INGOT_AGENT_TASKLIST,
            INGOT_AGENT_TASKLIST_REFINER,
        )

        assert mock_state.subagent_names["planner"] == INGOT_AGENT_PLANNER
        assert mock_state.subagent_names["tasklist"] == INGOT_AGENT_TASKLIST
        assert mock_state.subagent_names["tasklist_refiner"] == INGOT_AGENT_TASKLIST_REFINER
        assert mock_state.subagent_names["implementer"] == INGOT_AGENT_IMPLEMENTER
        assert mock_state.subagent_names["reviewer"] == INGOT_AGENT_REVIEWER
        assert mock_state.subagent_names["doc_updater"] == INGOT_AGENT_DOC_UPDATER

    def test_all_subagent_keys_present(self, mock_state):
        expected_keys = {
            "planner",
            "tasklist",
            "tasklist_refiner",
            "implementer",
            "reviewer",
            "fixer",
            "doc_updater",
        }
        assert set(mock_state.subagent_names.keys()) == expected_keys


class TestParallelExecutionSemantics:
    """Capture parallel execution behavior in Step 3.

    These tests verify that parallel task execution maintains
    session independence. Each task must have its own client instance.
    """

    def test_parallel_tasks_use_independent_clients(self):
        from ingot.integrations.auggie import AuggieClient

        # Create two independent clients (simulating parallel execution)
        client1 = AuggieClient()
        client2 = AuggieClient()

        # They should be independent instances
        assert client1 is not client2, "Parallel tasks must use different client instances"

    def test_dont_save_session_parameter_available(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        sig = inspect.signature(client.run_with_callback)

        assert (
            "dont_save_session" in sig.parameters
        ), "run_with_callback must have dont_save_session parameter"

    def test_dont_save_session_default_is_false(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()
        sig = inspect.signature(client.run_with_callback)

        param = sig.parameters["dont_save_session"]
        assert param.default is False, "dont_save_session should default to False"

    def test_client_model_isolation(self):
        from ingot.integrations.auggie import AuggieClient

        client1 = AuggieClient(model="model-a")
        client2 = AuggieClient(model="model-b")

        assert client1.model == "model-a"
        assert client2.model == "model-b"
        assert client1.model != client2.model

    def test_agent_parameter_available_in_run_methods(self):
        from ingot.integrations.auggie import AuggieClient

        client = AuggieClient()

        methods_with_agent = [
            "run",
            "run_print",
            "run_print_quiet",
            "run_print_with_output",
            "run_with_callback",
        ]

        for method_name in methods_with_agent:
            method = getattr(client, method_name)
            sig = inspect.signature(method)
            assert "agent" in sig.parameters, f"{method_name} must have agent parameter"

    def test_concurrent_clients_no_interference(self, monkeypatch):
        import concurrent.futures

        from ingot.integrations.auggie import AuggieClient

        calls: list[tuple[int, str, bool]] = []

        def fake_run_with_callback(
            self, command, output_callback=None, dont_save_session=False, **kwargs
        ):
            calls.append((id(self), command, dont_save_session))
            if output_callback:
                output_callback(f"CALL:{command}")
            return True, f"OUTPUT:{command}"

        monkeypatch.setattr(AuggieClient, "run_with_callback", fake_run_with_callback)

        def run_client(client_id: int) -> tuple[int, bool, str]:
            client = AuggieClient()
            success, output = client.run_with_callback(
                f"Say exactly: CLIENT_{client_id}_OK",
                output_callback=lambda x: None,
                dont_save_session=True,
            )
            return client_id, success, output

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_client, i) for i in range(2)]
            results = [f.result(timeout=30) for f in futures]

        # Verify both completed and returned expected types
        assert len(results) == 2, "Both clients should complete"
        for client_id, success, output in results:
            assert isinstance(success, bool), f"Client {client_id} should return bool"
            assert isinstance(output, str), f"Client {client_id} should return str"
            assert success is True, f"Client {client_id} should report success"

        # Verify calls were recorded for two distinct client instances
        client_ids_seen = {client_obj_id for client_obj_id, _, _ in calls}
        assert len(client_ids_seen) == 2, "Parallel tasks must use different client instances"
        assert all(
            flag is True for _, _, flag in calls
        ), "dont_save_session must be honored in parallel tasks"
