"""Tests for error analysis module."""

import pytest

from ingot.utils.error_analysis import ErrorAnalysis, analyze_error_output
from ingot.workflow.tasks import Task, TaskStatus


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task for testing."""
    return Task(name="Test task", status=TaskStatus.PENDING)


class TestErrorAnalysis:
    def test_to_markdown(self) -> None:
        error = ErrorAnalysis(
            error_type="syntax",
            file_path="test.py",
            line_number=42,
            error_message="SyntaxError: invalid syntax",
            stack_trace=["line 1", "line 2"],
            root_cause="Missing colon",
            suggested_fix="Add colon at end of line",
        )

        markdown = error.to_markdown()
        assert "**Type:** syntax" in markdown
        assert "**File:** test.py" in markdown
        assert "**Line:** 42" in markdown
        assert "SyntaxError: invalid syntax" in markdown
        assert "Missing colon" in markdown
        assert "Add colon at end of line" in markdown


class TestParsePythonTraceback:
    def test_parse_name_error(self, sample_task: Task) -> None:
        output = """
Traceback (most recent call last):
  File "/path/to/file.py", line 42, in <module>
    print(undefined_var)
NameError: name 'undefined_var' is not defined
"""
        result = analyze_error_output(output, sample_task)

        assert result.error_type == "name_error"
        assert result.file_path == "/path/to/file.py"
        assert result.line_number == 42
        assert "NameError" in result.error_message
        assert "undefined_var" in result.error_message

    def test_parse_type_error(self, sample_task: Task) -> None:
        output = """
Traceback (most recent call last):
  File "/app/main.py", line 10, in process
    result = "string" + 123
TypeError: can only concatenate str (not "int") to str
"""
        result = analyze_error_output(output, sample_task)

        assert result.error_type == "type_error"
        assert result.file_path == "/app/main.py"
        assert result.line_number == 10
        assert "TypeError" in result.error_message

    def test_parse_attribute_error(self, sample_task: Task) -> None:
        output = """
Traceback (most recent call last):
  File "service.py", line 25, in get_data
    return obj.missing_attribute
AttributeError: 'NoneType' object has no attribute 'missing_attribute'
"""
        result = analyze_error_output(output, sample_task)

        assert result.error_type == "attribute_error"
        assert "AttributeError" in result.error_message
        assert "missing_attribute" in result.error_message


class TestParseTypeScriptError:
    def test_parse_ts_compiler_error(self, sample_task: Task) -> None:
        # The parser expects: file.ts(line,col): error TSxxxx: message
        # Note: Detection pattern checks for ".ts(" so we need .ts not .tsx
        output = "src/components/Button.ts(15,7): error TS2322: Type 'string' is not assignable to type 'number'."

        result = analyze_error_output(output, sample_task)

        assert result.error_type == "typescript_type"  # More specific type
        assert result.file_path == "src/components/Button.ts"
        assert result.line_number == 15
        assert "TS2322" in result.error_message

    def test_parse_ts_name_error(self, sample_task: Task) -> None:
        output = "src/utils/helper.ts(42,10): error TS2304: Cannot find name 'foo'."

        result = analyze_error_output(output, sample_task)

        assert result.error_type == "typescript_name"
        assert result.file_path == "src/utils/helper.ts"
        assert result.line_number == 42


class TestParseTestFailure:
    def test_parse_pytest_failure(self, sample_task: Task) -> None:
        # The parser expects: FAILED file::test - error message
        output = "FAILED tests/test_api.py::test_get_user - AssertionError: assert 404 == 200"

        result = analyze_error_output(output, sample_task)

        assert result.error_type == "test_failure"
        assert result.file_path == "tests/test_api.py"
        assert "test_get_user" in result.error_message

    def test_parse_test_failure_without_specific_format(self, sample_task: Task) -> None:
        # Without the specific format, it won't be parsed as test_failure
        output = "FAILED: Some generic failure message"

        result = analyze_error_output(output, sample_task)

        # Falls back to unknown since it doesn't match the regex pattern
        assert result.error_type == "unknown"


class TestParseImportError:
    def test_parse_module_not_found(self, sample_task: Task) -> None:
        output = """
Traceback (most recent call last):
  File "app.py", line 5, in <module>
    from missing_module import something
ModuleNotFoundError: No module named 'missing_module'
"""
        result = analyze_error_output(output, sample_task)

        assert result.error_type == "import"
        assert "missing_module" in result.error_message


class TestParseSyntaxError:
    def test_parse_python_syntax_error(self, sample_task: Task) -> None:
        output = """
  File "bad_syntax.py", line 10
    if True
           ^
SyntaxError: invalid syntax
"""
        result = analyze_error_output(output, sample_task)

        assert result.error_type == "syntax"
        assert "SyntaxError" in result.error_message


class TestGenericError:
    def test_unknown_error_type(self, sample_task: Task) -> None:
        output = "Some random error message that doesn't match any pattern"

        result = analyze_error_output(output, sample_task)

        assert result.error_type == "unknown"
        assert result.file_path is None
        assert result.line_number is None
        assert len(result.error_message) > 0
