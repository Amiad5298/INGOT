"""Tests for ai_workflow.integrations.auggie module."""

import pytest
from unittest.mock import MagicMock, patch
import subprocess

from ai_workflow.integrations.auggie import (
    AuggieModel,
    AuggieClient,
    version_gte,
    extract_model_id,
    get_auggie_version,
    get_node_version,
    check_auggie_installed,
    list_models,
    _parse_model_list,
)


class TestVersionGte:
    """Tests for version_gte function."""

    def test_equal_versions(self):
        """Equal versions return True."""
        assert version_gte("1.0.0", "1.0.0") is True

    def test_greater_major(self):
        """Greater major version returns True."""
        assert version_gte("2.0.0", "1.0.0") is True

    def test_greater_minor(self):
        """Greater minor version returns True."""
        assert version_gte("1.2.0", "1.1.0") is True

    def test_greater_patch(self):
        """Greater patch version returns True."""
        assert version_gte("1.0.2", "1.0.1") is True

    def test_lesser_version(self):
        """Lesser version returns False."""
        assert version_gte("1.0.0", "2.0.0") is False

    def test_handles_two_part_version(self):
        """Handles versions with only major.minor."""
        assert version_gte("1.2", "1.1") is True
        assert version_gte("1.1", "1.2") is False

    def test_handles_prerelease(self):
        """Handles prerelease versions."""
        assert version_gte("1.0.0", "1.0.0-beta") is True


class TestGetAuggieVersion:
    """Tests for get_auggie_version function."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_returns_version(self, mock_run, mock_which):
        """Returns version string when installed."""
        mock_which.return_value = "/usr/bin/auggie"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="auggie version 0.12.0\n",
        )
        
        result = get_auggie_version()
        
        assert result == "0.12.0"

    @patch("shutil.which")
    def test_returns_none_when_not_installed(self, mock_which):
        """Returns None when auggie not in PATH."""
        mock_which.return_value = None
        
        result = get_auggie_version()
        
        assert result is None


class TestGetNodeVersion:
    """Tests for get_node_version function."""

    @patch("shutil.which")
    @patch("subprocess.run")
    def test_returns_version(self, mock_run, mock_which):
        """Returns version string when installed."""
        mock_which.return_value = "/usr/bin/node"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="v22.0.0\n",
        )
        
        result = get_node_version()
        
        assert result == "22.0.0"

    @patch("shutil.which")
    def test_returns_none_when_not_installed(self, mock_which):
        """Returns None when node not in PATH."""
        mock_which.return_value = None
        
        result = get_node_version()
        
        assert result is None


class TestCheckAuggieInstalled:
    """Tests for check_auggie_installed function."""

    @patch("ai_workflow.integrations.auggie.get_auggie_version")
    @patch("ai_workflow.integrations.auggie.print_step")
    @patch("ai_workflow.integrations.auggie.print_info")
    @patch("ai_workflow.integrations.auggie.print_success")
    def test_returns_true_when_valid(self, mock_success, mock_info, mock_step, mock_version):
        """Returns True when version meets requirements."""
        mock_version.return_value = "0.12.0"
        
        is_valid, message = check_auggie_installed()
        
        assert is_valid is True
        assert message == ""

    @patch("ai_workflow.integrations.auggie.get_auggie_version")
    @patch("ai_workflow.integrations.auggie.print_step")
    def test_returns_false_when_not_installed(self, mock_step, mock_version):
        """Returns False when not installed."""
        mock_version.return_value = None
        
        is_valid, message = check_auggie_installed()
        
        assert is_valid is False
        assert "not installed" in message

    @patch("ai_workflow.integrations.auggie.get_auggie_version")
    @patch("ai_workflow.integrations.auggie.print_step")
    @patch("ai_workflow.integrations.auggie.print_info")
    def test_returns_false_when_old_version(self, mock_info, mock_step, mock_version):
        """Returns False when version is too old."""
        mock_version.return_value = "0.10.0"
        
        is_valid, message = check_auggie_installed()
        
        assert is_valid is False
        assert "older than" in message


class TestAuggieClient:
    """Tests for AuggieClient class."""

    def test_init_with_model_id(self):
        """Initializes with model ID."""
        client = AuggieClient(model="opus4.5")

        assert client.model == "opus4.5"

    def test_init_with_full_model_name(self):
        """Extracts model ID from full name format."""
        client = AuggieClient(model="Claude Opus 4.5 [opus4.5]")

        assert client.model == "opus4.5"

    def test_init_without_model(self):
        """Initializes with empty model."""
        client = AuggieClient()

        assert client.model == ""

    @patch("subprocess.run")
    def test_run_basic_command(self, mock_run):
        """Runs basic command."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output")
        client = AuggieClient()
        
        result = client.run("test prompt")
        
        mock_run.assert_called_once()
        assert "auggie" in mock_run.call_args[0][0]

    @patch("subprocess.run")
    def test_run_with_model(self, mock_run):
        """Includes model flag when set."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output")
        client = AuggieClient(model="claude-3")
        
        client.run("test prompt")
        
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        assert "claude-3" in cmd

    @patch("subprocess.run")
    def test_run_print_returns_success(self, mock_run):
        """run_print returns True on success."""
        mock_run.return_value = MagicMock(returncode=0)
        client = AuggieClient()
        
        result = client.run_print("test prompt")
        
        assert result is True

    @patch("subprocess.run")
    def test_run_print_quiet_returns_output(self, mock_run):
        """run_print_quiet returns stdout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="test output")
        client = AuggieClient()

        result = client.run_print_quiet("test prompt")

        assert result == "test output"

    @patch("subprocess.run")
    def test_run_print_quiet_captures_output(self, mock_run):
        """run_print_quiet uses capture_output=True to capture stdout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="test output")
        client = AuggieClient()

        client.run_print_quiet("test prompt")

        # Verify capture_output=True was used
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("capture_output") is True

    @patch("subprocess.run")
    def test_run_print_without_quiet_does_not_capture(self, mock_run):
        """run_print without quiet flag does not capture output."""
        mock_run.return_value = MagicMock(returncode=0)
        client = AuggieClient()

        client.run_print("test prompt")

        # Verify capture_output=False was used
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("capture_output") is False


class TestExtractModelId:
    """Tests for extract_model_id function."""

    def test_extracts_id_from_full_format(self):
        """Extracts model ID from 'Name [id]' format."""
        assert extract_model_id("Claude Opus 4.5 [opus4.5]") == "opus4.5"
        assert extract_model_id("Haiku 4.5 [haiku4.5]") == "haiku4.5"
        assert extract_model_id("GPT-5 [gpt5]") == "gpt5"

    def test_returns_id_only_format_unchanged(self):
        """Returns ID-only format unchanged."""
        assert extract_model_id("opus4.5") == "opus4.5"
        assert extract_model_id("haiku4.5") == "haiku4.5"
        assert extract_model_id("gpt5") == "gpt5"

    def test_handles_empty_string(self):
        """Returns empty string for empty input."""
        assert extract_model_id("") == ""

    def test_handles_whitespace(self):
        """Strips whitespace from input."""
        assert extract_model_id("  opus4.5  ") == "opus4.5"
        assert extract_model_id("  Claude Opus 4.5 [opus4.5]  ") == "opus4.5"


class TestBuildCommand:
    """Tests for AuggieClient._build_command method."""

    def test_basic_command(self):
        """Builds basic command with prompt only."""
        client = AuggieClient()
        cmd = client._build_command("test prompt")

        assert cmd == ["auggie", "test prompt"]

    def test_with_model(self):
        """Includes model flag when set."""
        client = AuggieClient(model="claude-3")
        cmd = client._build_command("test prompt")

        assert cmd == ["auggie", "--model", "claude-3", "test prompt"]

    def test_with_model_override(self):
        """Model parameter overrides client default."""
        client = AuggieClient(model="claude-3")
        cmd = client._build_command("test prompt", model="gpt-4")

        assert cmd == ["auggie", "--model", "gpt-4", "test prompt"]

    def test_with_print_mode(self):
        """Includes --print flag when enabled."""
        client = AuggieClient()
        cmd = client._build_command("test prompt", print_mode=True)

        assert "--print" in cmd

    def test_with_quiet(self):
        """Includes --quiet flag when enabled."""
        client = AuggieClient()
        cmd = client._build_command("test prompt", quiet=True)

        assert "--quiet" in cmd

    def test_with_dont_save_session(self):
        """Includes --dont-save-session flag when enabled."""
        client = AuggieClient()
        cmd = client._build_command("test prompt", dont_save_session=True)

        assert "--dont-save-session" in cmd

    def test_all_flags_combined(self):
        """Combines all flags correctly."""
        client = AuggieClient(model="claude-3")
        cmd = client._build_command(
            "test prompt",
            print_mode=True,
            quiet=True,
            dont_save_session=True,
        )

        assert "--model" in cmd
        assert "claude-3" in cmd
        assert "--print" in cmd
        assert "--quiet" in cmd
        assert "--dont-save-session" in cmd
        assert cmd[-1] == "test prompt"


class TestRunWithCallback:
    """Tests for AuggieClient.run_with_callback method."""

    @patch("subprocess.Popen")
    def test_calls_callback_for_each_line(self, mock_popen):
        """Callback is invoked for each output line."""
        # Setup mock process
        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n", "line 3\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        client = AuggieClient()
        callback_lines = []

        success, output = client.run_with_callback(
            "test prompt",
            output_callback=lambda line: callback_lines.append(line),
        )

        assert callback_lines == ["line 1", "line 2", "line 3"]
        assert success is True

    @patch("subprocess.Popen")
    def test_returns_full_output(self, mock_popen):
        """Returns complete output as second return value."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        client = AuggieClient()

        success, output = client.run_with_callback(
            "test prompt",
            output_callback=lambda line: None,
        )

        assert output == "line 1\nline 2\n"

    @patch("subprocess.Popen")
    def test_returns_false_on_failure(self, mock_popen):
        """Returns False when command fails."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["error output\n"])
        mock_process.returncode = 1
        mock_process.wait.return_value = 1
        mock_popen.return_value = mock_process

        client = AuggieClient()

        success, output = client.run_with_callback(
            "test prompt",
            output_callback=lambda line: None,
        )

        assert success is False
        assert output == "error output\n"

    @patch("subprocess.Popen")
    def test_uses_correct_subprocess_args(self, mock_popen):
        """Popen is called with correct arguments for streaming."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        client = AuggieClient()

        client.run_with_callback(
            "test prompt",
            output_callback=lambda line: None,
        )

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["stdin"] == subprocess.DEVNULL
        assert call_kwargs["stdout"] == subprocess.PIPE
        assert call_kwargs["stderr"] == subprocess.STDOUT
        assert call_kwargs["text"] is True
        assert call_kwargs["bufsize"] == 1

    @patch("subprocess.Popen")
    def test_passes_model_to_command(self, mock_popen):
        """Model is included in command."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        client = AuggieClient(model="claude-3")

        client.run_with_callback(
            "test prompt",
            output_callback=lambda line: None,
        )

        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        assert "claude-3" in cmd

    @patch("subprocess.Popen")
    def test_strips_newlines_from_callback(self, mock_popen):
        """Newlines are stripped before passing to callback."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["line with trailing newline\n"])
        mock_process.returncode = 0
        mock_process.wait.return_value = 0
        mock_popen.return_value = mock_process

        client = AuggieClient()
        callback_lines = []

        client.run_with_callback(
            "test prompt",
            output_callback=lambda line: callback_lines.append(line),
        )

        # Callback receives line without newline
        assert callback_lines == ["line with trailing newline"]


class TestParseModelList:
    """Tests for _parse_model_list function."""

    def test_parses_model_list(self):
        """Parses model list output."""
        output = """Available models:
 - Claude 3 Opus [claude-3-opus]
 - Claude 3 Sonnet [claude-3-sonnet]
 * Haiku 4.5 [haiku4.5]
"""

        models = _parse_model_list(output)

        assert len(models) == 3
        assert models[0].name == "Claude 3 Opus"
        assert models[0].id == "claude-3-opus"

    def test_handles_empty_output(self):
        """Returns empty list for empty output."""
        models = _parse_model_list("")

        assert models == []

