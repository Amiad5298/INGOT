"""Self-tests for the FakeBackend test helper.

Validates that FakeBackend correctly implements the AIBackend protocol
and that all its test-support features (call recording, configurable
responses, convenience factories) work as documented.
"""

from __future__ import annotations

import pytest

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import AIBackend
from tests.fakes.fake_backend import (
    FakeBackend,
    make_failing_backend,
    make_rate_limited_backend,
    make_successful_backend,
)


class TestFakeBackendProtocol:
    def test_isinstance_aibackend(self):
        fb = FakeBackend([(True, "ok")])
        assert isinstance(fb, AIBackend)

    def test_has_all_protocol_methods(self):
        fb = FakeBackend([(True, "ok")])
        for attr in (
            "name",
            "platform",
            "model",
            "supports_parallel",
            "run_with_callback",
            "run_print_with_output",
            "run_print_quiet",
            "run_streaming",
            "check_installed",
            "detect_rate_limit",
            "supports_parallel_execution",
            "close",
        ):
            assert hasattr(fb, attr), f"Missing protocol member: {attr}"


class TestFakeBackendResponses:
    def test_returns_responses_in_order(self):
        fb = FakeBackend([(True, "first"), (False, "second")])
        assert fb.run_print_with_output("p1") == (True, "first")
        assert fb.run_print_with_output("p2") == (False, "second")

    def test_exhaustion_raises_index_error(self):
        fb = FakeBackend([(True, "only")])
        fb.run_print_with_output("p1")
        with pytest.raises(IndexError, match="FakeBackend exhausted"):
            fb.run_print_with_output("p2")

    def test_call_count_increments(self):
        fb = FakeBackend([(True, "a"), (True, "b"), (True, "c"), (True, "d")])
        fb.run_print_with_output("p")
        fb.run_print_quiet("p")
        fb.run_streaming("p")
        fb.run_with_callback("p", output_callback=lambda _: None)
        assert fb.call_count == 4


class TestFakeBackendCallRecording:
    def test_run_with_callback_recorded(self):
        fb = FakeBackend([(True, "out")])
        fb.run_with_callback("hello", output_callback=lambda _: None, model="gpt-4")
        assert len(fb.calls) == 1
        prompt, kwargs = fb.calls[0]
        assert prompt == "hello"
        assert kwargs["model"] == "gpt-4"

    def test_run_print_quiet_recorded(self):
        fb = FakeBackend([(True, "out")])
        fb.run_print_quiet("quiet prompt", subagent="planner")
        assert len(fb.quiet_calls) == 1
        prompt, kwargs = fb.quiet_calls[0]
        assert prompt == "quiet prompt"
        assert kwargs["subagent"] == "planner"

    def test_run_print_with_output_recorded(self):
        fb = FakeBackend([(True, "out")])
        fb.run_print_with_output("loud prompt")
        assert len(fb.print_with_output_calls) == 1
        assert fb.print_with_output_calls[0][0] == "loud prompt"

    def test_run_streaming_recorded(self):
        fb = FakeBackend([(True, "out")])
        fb.run_streaming("stream prompt")
        assert len(fb.streaming_calls) == 1
        assert fb.streaming_calls[0][0] == "stream prompt"


class TestFakeBackendStreamingCallback:
    def test_callback_called_per_line(self):
        lines_received: list[str] = []
        fb = FakeBackend([(True, "line1\nline2\nline3")])
        fb.run_with_callback("p", output_callback=lines_received.append)
        assert lines_received == ["line1", "line2", "line3"]

    def test_callback_single_line(self):
        lines_received: list[str] = []
        fb = FakeBackend([(True, "single")])
        fb.run_with_callback("p", output_callback=lines_received.append)
        assert lines_received == ["single"]

    def test_callback_returns_full_output(self):
        fb = FakeBackend([(True, "line1\nline2")])
        success, output = fb.run_with_callback("p", output_callback=lambda _: None)
        assert success is True
        assert output == "line1\nline2"


class TestFakeBackendProperties:
    def test_default_name(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.name == "FakeBackend"

    def test_custom_name(self):
        fb = FakeBackend([(True, "ok")], name="CustomBot")
        assert fb.name == "CustomBot"

    def test_default_platform(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.platform == AgentPlatform.AUGGIE

    def test_custom_platform(self):
        fb = FakeBackend([(True, "ok")], platform=AgentPlatform.CLAUDE)
        assert fb.platform == AgentPlatform.CLAUDE

    def test_default_supports_parallel(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.supports_parallel is True

    def test_custom_supports_parallel(self):
        fb = FakeBackend([(True, "ok")], supports_parallel=False)
        assert fb.supports_parallel is False

    def test_supports_parallel_execution_delegates(self):
        fb = FakeBackend([(True, "ok")], supports_parallel=False)
        assert fb.supports_parallel_execution() is False

    def test_model_returns_empty_string(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.model == ""


class TestFakeBackendClose:
    def test_close_lifecycle(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.closed is False
        fb.close()
        assert fb.closed is True
        fb.close()  # idempotent
        assert fb.closed is True


class TestFakeBackendCheckInstalled:
    def test_installed_true(self):
        fb = FakeBackend([(True, "ok")], installed=True)
        installed, msg = fb.check_installed()
        assert installed is True
        assert "1.0.0" in msg

    def test_installed_false(self):
        fb = FakeBackend([(True, "ok")], installed=False)
        installed, msg = fb.check_installed()
        assert installed is False
        assert "not installed" in msg.lower()


class TestFakeBackendDetectRateLimit:
    def test_detects_429(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.detect_rate_limit("Error 429: rate limit hit") is True

    def test_detects_rate_limit_keyword(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.detect_rate_limit("You hit the rate limit") is True

    def test_normal_output_not_rate_limited(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.detect_rate_limit("Task completed successfully") is False

    def test_empty_output_not_rate_limited(self):
        fb = FakeBackend([(True, "ok")])
        assert fb.detect_rate_limit("") is False


class TestConvenienceFactories:
    def test_make_successful_backend_default(self):
        fb = make_successful_backend()
        result = fb.run_print_with_output("p")
        assert result == (True, "success")

    def test_make_successful_backend_custom_output(self):
        fb = make_successful_backend("custom result")
        result = fb.run_print_with_output("p")
        assert result == (True, "custom result")

    def test_make_failing_backend_default(self):
        fb = make_failing_backend()
        result = fb.run_print_with_output("p")
        assert result == (False, "error")

    def test_make_failing_backend_custom_error(self):
        fb = make_failing_backend("custom error")
        result = fb.run_print_with_output("p")
        assert result == (False, "custom error")

    def test_make_rate_limited_backend_default(self):
        fb = make_rate_limited_backend()
        r1 = fb.run_print_with_output("p1")
        r2 = fb.run_print_with_output("p2")
        r3 = fb.run_print_with_output("p3")
        assert r1 == (False, "Error 429: rate limit hit")
        assert r2 == (False, "Error 429: rate limit hit")
        assert r3 == (True, "Task completed successfully")

    def test_make_rate_limited_backend_custom_count(self):
        fb = make_rate_limited_backend(fail_count=1)
        r1 = fb.run_print_with_output("p1")
        r2 = fb.run_print_with_output("p2")
        assert r1[0] is False
        assert r2[0] is True

    def test_factories_return_fakebackend_instances(self):
        assert isinstance(make_successful_backend(), FakeBackend)
        assert isinstance(make_failing_backend(), FakeBackend)
        assert isinstance(make_rate_limited_backend(), FakeBackend)


class TestFakeBackendEdgeCases:
    def test_empty_responses_fails_immediately(self):
        fb = FakeBackend([])
        with pytest.raises(IndexError, match="FakeBackend exhausted"):
            fb.run_print_with_output("p")

    def test_empty_responses_all_methods_fail(self):
        for method_name, call_kwargs in [
            ("run_print_quiet", {}),
            ("run_streaming", {}),
            ("run_with_callback", {"output_callback": lambda _: None}),
        ]:
            fb = FakeBackend([])
            with pytest.raises(IndexError):
                getattr(fb, method_name)("p", **call_kwargs)

    @pytest.mark.parametrize(
        "method,call_list_attr,extra_kwargs",
        [
            ("run_with_callback", "calls", {"output_callback": lambda _: None}),
            ("run_print_with_output", "print_with_output_calls", {}),
            ("run_print_quiet", "quiet_calls", {}),
            ("run_streaming", "streaming_calls", {}),
        ],
    )
    def test_model_kwarg_recorded(self, method: str, call_list_attr: str, extra_kwargs: dict):
        fb = FakeBackend([(True, "ok")])
        getattr(fb, method)("p", model="test-model", **extra_kwargs)
        call_list = getattr(fb, call_list_attr)
        assert call_list[0][1]["model"] == "test-model"

    def test_model_none_by_default(self):
        fb = FakeBackend([(True, "ok")])
        fb.run_print_with_output("p")
        assert fb.print_with_output_calls[0][1]["model"] is None

    def test_subagent_recorded(self):
        fb = FakeBackend([(True, "a"), (True, "b")])
        fb.run_print_with_output("p", subagent="ingot-planner")
        fb.run_with_callback("p", output_callback=lambda _: None, subagent="ingot-implementer")
        assert fb.print_with_output_calls[0][1]["subagent"] == "ingot-planner"
        assert fb.calls[0][1]["subagent"] == "ingot-implementer"

    def test_timeout_seconds_recorded(self):
        fb = FakeBackend([(True, "ok")])
        fb.run_with_callback("p", output_callback=lambda _: None, timeout_seconds=30.0)
        assert fb.calls[0][1]["timeout_seconds"] == 30.0

    def test_callback_with_empty_output(self):
        lines: list[str] = []
        fb = FakeBackend([(True, "")])
        success, output = fb.run_with_callback("p", output_callback=lines.append)
        assert success is True
        assert output == ""
        assert lines == []

    def test_mixed_method_calls_share_call_count(self):
        fb = FakeBackend([(True, "a"), (True, "b"), (True, "c")])
        fb.run_print_with_output("p1")
        fb.run_print_quiet("p2")
        fb.run_streaming("p3")
        assert fb.call_count == 3
        assert len(fb.print_with_output_calls) == 1
        assert len(fb.quiet_calls) == 1
        assert len(fb.streaming_calls) == 1
