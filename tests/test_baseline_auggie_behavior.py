"""Baseline behavior tests for Auggie workflow.

These tests capture the current behavior of AuggieClient and workflow steps
BEFORE the multi-backend refactoring. They serve as regression tests to ensure
the new AIBackend abstraction maintains identical semantics.

Run with: SPEC_INTEGRATION_TESTS=1 pytest tests/test_baseline_auggie_behavior.py -v

IMPORTANT: All tests in this file must pass with the current codebase
before proceeding to Phase 1 of the multi-backend refactoring.
"""

import inspect
import os
import subprocess

import pytest

# Marker for tests that require running the Auggie CLI (integration/CLI tests)
requires_integration = pytest.mark.skipif(
    os.environ.get("SPEC_INTEGRATION_TESTS") != "1",
    reason="Integration tests require SPEC_INTEGRATION_TESTS=1",
)


class TestImportability:
    """Verify that required functions and classes are importable.

    These tests ensure that the baseline tests can actually import
    the functions they need to test. This catches issues where
    private functions are not accessible.
    """

    def testlooks_like_rate_limit_is_importable(self):
        """Verify looks_like_rate_limit can be imported.

        Contract: The private function must be accessible for testing.
        If this fails, the function may have been renamed or made truly private.
        """
        try:
            from spec.integrations.auggie import looks_like_rate_limit

            assert callable(looks_like_rate_limit), "Must be callable"
        except ImportError as e:
            pytest.fail(
                f"Cannot import looks_like_rate_limit: {e}\n"
                "This function is required for rate limit detection tests."
            )

    def test_auggie_client_is_importable(self):
        """Verify AuggieClient can be imported."""
        try:
            from spec.integrations.auggie import AuggieClient

            assert AuggieClient is not None
        except ImportError as e:
            pytest.fail(f"Cannot import AuggieClient: {e}")

    def test_specflow_agent_constants_are_importable(self):
        """Verify SPECFLOW_AGENT_* constants can be imported."""
        try:
            from spec.workflow.constants import (
                SPECFLOW_AGENT_DOC_UPDATER,
                SPECFLOW_AGENT_IMPLEMENTER,
                SPECFLOW_AGENT_PLANNER,
                SPECFLOW_AGENT_REVIEWER,
                SPECFLOW_AGENT_TASKLIST,
                SPECFLOW_AGENT_TASKLIST_REFINER,
            )

            # Verify they are strings
            for const in [
                SPECFLOW_AGENT_PLANNER,
                SPECFLOW_AGENT_TASKLIST,
                SPECFLOW_AGENT_TASKLIST_REFINER,
                SPECFLOW_AGENT_IMPLEMENTER,
                SPECFLOW_AGENT_REVIEWER,
                SPECFLOW_AGENT_DOC_UPDATER,
            ]:
                assert isinstance(const, str), f"Constant must be str: {const}"
        except ImportError as e:
            pytest.fail(f"Cannot import SPECFLOW_AGENT_* constants: {e}")


@requires_integration
class TestAuggieClientSemantics:
    """Capture current AuggieClient method semantics.

    These tests verify the EXACT return types and behaviors of AuggieClient
    methods. Any new backend implementation MUST match these semantics.

    NOTE: These tests require the Auggie CLI and are skipped unless
    SPEC_INTEGRATION_TESTS=1 is set.
    """

    def test_run_with_callback_returns_tuple_bool_str(self):
        """Verify run_with_callback returns (bool, str) tuple.

        Contract:
        - Returns tuple[bool, str]
        - First element is success (True if returncode == 0)
        - Second element is full output (all lines concatenated)
        - Callback is invoked for each line (stripped of newline) when successful
        """
        from spec.integrations.auggie import AuggieClient

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
        """Verify run_with_callback always returns a 2-tuple (bool, str)."""
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        result = client.run_with_callback(
            "Say exactly: BASELINE_TEST_OK",
            output_callback=lambda _: None,
            dont_save_session=True,
        )

        assert isinstance(result, tuple), "Return value must be a tuple"
        assert len(result) == 2, "Tuple must have exactly two elements"

    def test_run_print_with_output_returns_tuple_bool_str(self):
        """Verify run_print_with_output returns (bool, str) tuple.

        Contract:
        - Returns tuple[bool, str]
        - Wraps run_with_callback internally
        - Prints output to terminal in real-time
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        success, output = client.run_print_with_output(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(success, bool), "First element must be bool"
        assert isinstance(output, str), "Second element must be str"

    def test_run_print_quiet_returns_str(self):
        """Verify run_print_quiet returns str only.

        Contract:
        - Returns str (stdout only)
        - No success indicator (caller must check content)
        - Uses --print --quiet flags
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        output = client.run_print_quiet(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(output, str), "Must return str"

    def test_run_print_returns_bool(self):
        """Verify run_print returns bool only.

        Contract:
        - Returns bool (True if command succeeded, False otherwise)
        - Interactive mode - streams output to terminal
        - Used in clarification flow (step1_plan.py:296)
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        success = client.run_print(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(success, bool), "Must return bool"

    def test_run_returns_completed_process(self):
        """Verify run() returns subprocess.CompletedProcess.

        Contract:
        - Returns subprocess.CompletedProcess[str]
        - Has returncode attribute (0 = success)
        - Low-level method used by other run_* methods
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        result = client.run(
            "Say exactly: BASELINE_TEST_OK",
            dont_save_session=True,
        )

        assert isinstance(result, subprocess.CompletedProcess), "Must return CompletedProcess"
        assert isinstance(result.returncode, int), "returncode must be int"

    def test_callback_receives_lines_without_newlines(self):
        """Verify callback receives lines with newlines stripped.

        Contract:
        - Each line passed to callback has trailing newline removed
        - Full output in return value preserves newlines
        """
        from spec.integrations.auggie import AuggieClient

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
        """Verify full output preserves newlines while callback strips them.

        Contract:
        - Callback receives lines WITHOUT trailing newlines
        - Full output in return tuple PRESERVES newlines
        - Relationship: output contains lines joined with newlines
        """
        from spec.integrations.auggie import AuggieClient

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
        """Verify run_argv_with_callback returns False on CLI failure.

        Contract:
        - Returns (bool, str) tuple
        - success is False when command fails (returncode != 0)
        - Output is still captured even on failure (as str, possibly empty)

        NOTE: This test uses run_argv_with_callback (not run_with_callback)
        because run_with_callback embeds its input as a prompt string, NOT as
        CLI argv. To test deterministic CLI failure, we need raw argv control.

        The "--invalid-flag-xyz" is passed directly as a CLI flag to auggie,
        causing the CLI parser to reject it with a non-zero exit code.
        """
        from spec.integrations.auggie import AuggieClient

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
        """Verify HTTP 429 status code is detected."""
        from spec.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("Error 429: Too many requests")
        assert looks_like_rate_limit("HTTP/1.1 429")
        assert looks_like_rate_limit("Status: 429")

    def testlooks_like_rate_limit_explicit_messages(self):
        """Verify explicit rate limit messages are detected."""
        from spec.integrations.auggie import looks_like_rate_limit

        rate_limit_outputs = [
            "rate limit exceeded",
            "Rate limit hit, please wait",
            "rate_limit_error",
            "You have exceeded your rate limit",
        ]
        for output in rate_limit_outputs:
            assert looks_like_rate_limit(output), f"Should detect: {output}"

    def testlooks_like_rate_limit_quota_messages(self):
        """Verify quota exceeded messages are detected.

        Contract: Only "quota exceeded" pattern is matched, not just "quota".
        """
        from spec.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("quota exceeded for today")
        assert looks_like_rate_limit("Monthly quota exceeded")
        # Note: "API quota reached" does NOT match because pattern is "quota exceeded"
        assert not looks_like_rate_limit("API quota reached")

    def testlooks_like_rate_limit_capacity_messages(self):
        """Verify capacity-related messages are detected."""
        from spec.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("System at capacity")
        assert looks_like_rate_limit("Capacity limit reached")

    def testlooks_like_rate_limit_throttle_variants(self):
        """Verify throttle message variants are detected."""
        from spec.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("Request throttled")
        assert looks_like_rate_limit("Throttling in effect")
        assert looks_like_rate_limit("You are being throttled")

    def testlooks_like_rate_limit_server_errors(self):
        """Verify server error codes (often rate-limit related) are detected."""
        from spec.integrations.auggie import looks_like_rate_limit

        assert looks_like_rate_limit("502 Bad Gateway")
        assert looks_like_rate_limit("503 Service Unavailable")
        assert looks_like_rate_limit("504 Gateway Timeout")

    def testlooks_like_rate_limit_normal_success(self):
        """Verify normal success messages are NOT detected as rate limits."""
        from spec.integrations.auggie import looks_like_rate_limit

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

    def testlooks_like_rate_limit_false_positives_documented(self):
        """Document known false positives in current implementation.

        IMPORTANT: This test documents the CURRENT behavior, which includes
        false positives. The implementation uses simple substring matching
        that cannot distinguish context.

        Known false positives (these ARE detected as rate limits even though they shouldn't be):
        - "Error on line 429 of main.py" - contains "429"
        - "Expected 503 but got 200" - contains "503"
        - "Test case 502 failed" - contains "502"

        This is a known limitation that may be addressed in future versions.
        """
        from spec.integrations.auggie import looks_like_rate_limit

        # Document that these ARE false positives (current behavior)
        known_false_positives = [
            "Error on line 429 of main.py",  # 429 in context
            "Expected 503 but got 200",  # 503 in context
            "Test case 502 failed",  # 502 in context
        ]

        # These WILL be detected as rate limits (false positives)
        # This documents the current behavior for regression testing
        for output in known_false_positives:
            # Current implementation has false positives - document this
            result = looks_like_rate_limit(output)
            # Assert the CURRENT behavior (true = false positive exists)
            assert (
                result is True
            ), f"Documenting false positive: '{output}' should trigger rate limit detection"

    def testlooks_like_rate_limit_true_negatives(self):
        """Verify messages without rate-limit patterns are NOT detected."""
        from spec.integrations.auggie import looks_like_rate_limit

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
        """Verify detection is case-insensitive."""
        from spec.integrations.auggie import looks_like_rate_limit

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
        from spec.integrations.providers import GenericTicket, Platform
        from spec.workflow.state import WorkflowState

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
        """Verify the default planner subagent name.

        Contract: Step 1 (plan creation) uses 'spec-planner' subagent.
        """
        assert mock_state.subagent_names["planner"] == "spec-planner"

    def test_step2_uses_spec_tasklist_subagent(self, mock_state):
        """Verify the default tasklist subagent name.

        Contract: Step 2 (tasklist creation) uses 'spec-tasklist' subagent.
        """
        assert mock_state.subagent_names["tasklist"] == "spec-tasklist"

    def test_step2_refiner_uses_spec_tasklist_refiner(self, mock_state):
        """Verify the tasklist refiner subagent name.

        Contract: Tasklist refinement uses 'spec-tasklist-refiner' subagent.
        """
        assert mock_state.subagent_names["tasklist_refiner"] == "spec-tasklist-refiner"

    def test_step3_uses_spec_implementer_subagent(self, mock_state):
        """Verify the default implementer subagent name.

        Contract: Step 3 (task execution) uses 'spec-implementer' subagent.
        """
        assert mock_state.subagent_names["implementer"] == "spec-implementer"

    def test_step3_uses_spec_reviewer_subagent(self, mock_state):
        """Verify the reviewer subagent name.

        Contract: Task review uses 'spec-reviewer' subagent.
        """
        assert mock_state.subagent_names["reviewer"] == "spec-reviewer"

    def test_step4_uses_spec_doc_updater_subagent(self, mock_state):
        """Verify the doc updater subagent name.

        Contract: Step 4 (documentation) uses 'spec-doc-updater' subagent.
        """
        assert mock_state.subagent_names["doc_updater"] == "spec-doc-updater"

    def test_subagent_names_match_constants(self, mock_state):
        """Verify subagent names match the constants in spec.workflow.constants.

        Contract: WorkflowState defaults must match SPECFLOW_AGENT_* constants.
        """
        from spec.workflow.constants import (
            SPECFLOW_AGENT_DOC_UPDATER,
            SPECFLOW_AGENT_IMPLEMENTER,
            SPECFLOW_AGENT_PLANNER,
            SPECFLOW_AGENT_REVIEWER,
            SPECFLOW_AGENT_TASKLIST,
            SPECFLOW_AGENT_TASKLIST_REFINER,
        )

        assert mock_state.subagent_names["planner"] == SPECFLOW_AGENT_PLANNER
        assert mock_state.subagent_names["tasklist"] == SPECFLOW_AGENT_TASKLIST
        assert mock_state.subagent_names["tasklist_refiner"] == SPECFLOW_AGENT_TASKLIST_REFINER
        assert mock_state.subagent_names["implementer"] == SPECFLOW_AGENT_IMPLEMENTER
        assert mock_state.subagent_names["reviewer"] == SPECFLOW_AGENT_REVIEWER
        assert mock_state.subagent_names["doc_updater"] == SPECFLOW_AGENT_DOC_UPDATER

    def test_all_subagent_keys_present(self, mock_state):
        """Verify all expected subagent keys are present.

        Contract: WorkflowState must have all 7 subagent keys.
        """
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
        """Verify parallel tasks create independent AuggieClient instances.

        Contract: Each parallel task creates its own client instance.
        """
        from spec.integrations.auggie import AuggieClient

        # Create two independent clients (simulating parallel execution)
        client1 = AuggieClient()
        client2 = AuggieClient()

        # They should be independent instances
        assert client1 is not client2, "Parallel tasks must use different client instances"

    def test_dont_save_session_parameter_available(self):
        """Verify dont_save_session parameter exists in run_with_callback.

        Contract: run_with_callback must accept dont_save_session parameter.
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        sig = inspect.signature(client.run_with_callback)

        assert (
            "dont_save_session" in sig.parameters
        ), "run_with_callback must have dont_save_session parameter"

    def test_dont_save_session_default_is_false(self):
        """Verify dont_save_session defaults to False.

        Contract: By default, sessions are saved (for interactive use).
        Parallel execution explicitly sets dont_save_session=True.
        """
        from spec.integrations.auggie import AuggieClient

        client = AuggieClient()
        sig = inspect.signature(client.run_with_callback)

        param = sig.parameters["dont_save_session"]
        assert param.default is False, "dont_save_session should default to False"

    def test_client_model_isolation(self):
        """Verify each client can have different model settings.

        Contract: Model settings are instance-specific, not shared.
        """
        from spec.integrations.auggie import AuggieClient

        client1 = AuggieClient(model="model-a")
        client2 = AuggieClient(model="model-b")

        assert client1.model == "model-a"
        assert client2.model == "model-b"
        assert client1.model != client2.model

    def test_agent_parameter_available_in_run_methods(self):
        """Verify agent parameter exists in all run methods.

        Contract: All run methods must accept agent parameter for subagent dispatch.
        """
        from spec.integrations.auggie import AuggieClient

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
        """Verify concurrent clients remain independent without invoking the CLI.

        Contract: Parallel tasks must operate on independent client instances.
        This is an inspect-only test: it monkeypatches run_with_callback to
        avoid external Auggie calls while verifying per-instance invocation.
        """
        import concurrent.futures

        from spec.integrations.auggie import AuggieClient

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
