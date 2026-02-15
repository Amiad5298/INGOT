"""Tests for ingot.integrations.backends.base module."""

from collections.abc import Callable
from typing import Protocol

from ingot.config.fetch_config import AgentPlatform
from ingot.integrations.backends.base import AIBackend


class TestAIBackendProtocol:
    def test_aibackend_is_protocol(self):
        assert issubclass(AIBackend, Protocol)

    def test_aibackend_is_runtime_checkable(self):
        # The @runtime_checkable decorator enables isinstance
        assert hasattr(AIBackend, "__protocol_attrs__") or hasattr(
            AIBackend, "_is_runtime_protocol"
        )

    def test_protocol_has_name_property(self):
        assert "name" in dir(AIBackend)

    def test_protocol_has_platform_property(self):
        assert "platform" in dir(AIBackend)

    def test_protocol_has_supports_parallel_property(self):
        assert "supports_parallel" in dir(AIBackend)

    def test_protocol_has_run_with_callback_method(self):
        assert hasattr(AIBackend, "run_with_callback")
        assert callable(getattr(AIBackend, "run_with_callback", None))

    def test_protocol_has_run_print_with_output_method(self):
        assert hasattr(AIBackend, "run_print_with_output")

    def test_protocol_has_run_print_quiet_method(self):
        assert hasattr(AIBackend, "run_print_quiet")

    def test_protocol_has_run_streaming_method(self):
        assert hasattr(AIBackend, "run_streaming")

    def test_protocol_has_check_installed_method(self):
        assert hasattr(AIBackend, "check_installed")

    def test_protocol_has_detect_rate_limit_method(self):
        assert hasattr(AIBackend, "detect_rate_limit")

    def test_protocol_has_close_method(self):
        assert hasattr(AIBackend, "close")


class TestAIBackendCompliance:
    def test_fake_backend_satisfies_protocol(self):
        class FakeBackend:
            @property
            def name(self) -> str:
                return "Fake"

            @property
            def platform(self) -> AgentPlatform:
                return AgentPlatform.AUGGIE

            @property
            def model(self) -> str:
                return "test-model"

            @property
            def supports_parallel(self) -> bool:
                return True

            @property
            def supports_plan_mode(self) -> bool:
                return False

            def run_with_callback(
                self,
                prompt: str,
                *,
                output_callback: Callable[[str], None],
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
                plan_mode: bool = False,
            ) -> tuple[bool, str]:
                return True, "output"

            def run_print_with_output(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
                plan_mode: bool = False,
            ) -> tuple[bool, str]:
                return True, "output"

            def run_print_quiet(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                dont_save_session: bool = False,
                timeout_seconds: float | None = None,
                plan_mode: bool = False,
            ) -> str:
                return "output"

            def run_streaming(
                self,
                prompt: str,
                *,
                subagent: str | None = None,
                model: str | None = None,
                timeout_seconds: float | None = None,
                plan_mode: bool = False,
            ) -> tuple[bool, str]:
                return True, "output"

            def check_installed(self) -> tuple[bool, str]:
                return True, "Fake v1.0"

            def detect_rate_limit(self, output: str) -> bool:
                return False

            def list_models(self) -> list:
                return []

            def close(self) -> None:
                pass

        fake = FakeBackend()
        assert isinstance(fake, AIBackend)

    def test_incomplete_backend_does_not_satisfy_protocol(self):
        class IncompleteBackend:
            @property
            def name(self) -> str:
                return "Incomplete"

            # Missing other required methods/properties

        incomplete = IncompleteBackend()
        # isinstance check should fail for incomplete implementation
        assert not isinstance(incomplete, AIBackend)


class TestAIBackendImports:
    def test_aibackend_importable_from_package(self):
        from ingot.integrations.backends import AIBackend

        assert AIBackend is not None

    def test_all_exports_available(self):
        from ingot.integrations.backends import (
            AIBackend,
            BackendRateLimitError,
        )

        # Verify they're the correct classes
        assert AIBackend.__name__ == "AIBackend"
        assert BackendRateLimitError.__name__ == "BackendRateLimitError"
