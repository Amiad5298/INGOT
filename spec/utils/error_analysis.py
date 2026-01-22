"""
Error analysis implementation for better retry prompts.

This module provides structured error parsing and analysis to give
the AI agent better feedback when tasks fail.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec.workflow.tasks import Task


@dataclass
class ErrorAnalysis:
    """Structured error analysis."""
    error_type: str  # "syntax", "import", "runtime", "test_failure", "unknown"
    file_path: str | None
    line_number: int | None
    error_message: str
    stack_trace: list[str]
    root_cause: str
    suggested_fix: str

    def to_markdown(self) -> str:
        """Format as markdown for prompt."""
        return f"""
**Type:** {self.error_type}
**File:** {self.file_path or 'Unknown'}
**Line:** {self.line_number or 'Unknown'}

**Error Message:**
```
{self.error_message}
```

**Root Cause:**
{self.root_cause}

**Suggested Fix:**
{self.suggested_fix}

**Stack Trace:**
```
{chr(10).join(self.stack_trace[:10])}
```
"""


def analyze_error_output(output: str, task: "Task") -> ErrorAnalysis:
    """Parse and analyze error output to provide structured feedback.

    Args:
        output: Raw stdout/stderr from failed execution
        task: Task that failed

    Returns:
        Structured error analysis
    """
    # Try different parsers in order of specificity

    # Python traceback
    if "Traceback" in output:
        return _parse_python_traceback(output)

    # TypeScript error
    if "error TS" in output or ".ts(" in output:
        return _parse_typescript_error(output)

    # Jest/pytest test failure
    if "FAILED" in output or "AssertionError" in output:
        return _parse_test_failure(output)

    # Import error
    if "ModuleNotFoundError" in output or "Cannot find module" in output:
        return _parse_import_error(output)

    # Syntax error
    if "SyntaxError" in output or "Unexpected token" in output:
        return _parse_syntax_error(output)

    # Generic error
    return ErrorAnalysis(
        error_type="unknown",
        file_path=None,
        line_number=None,
        error_message=_extract_last_n_chars(output, 500),
        stack_trace=[],
        root_cause="Unable to determine root cause from error output",
        suggested_fix="Review the error output carefully and try again"
    )


def _parse_python_traceback(output: str) -> ErrorAnalysis:
    """Parse Python traceback."""
    lines = output.split('\n')

    # Find the traceback section
    traceback_start = -1
    for i, line in enumerate(lines):
        if "Traceback" in line:
            traceback_start = i
            break

    if traceback_start == -1:
        return _generic_error(output)

    # Extract stack trace
    stack_trace = []
    error_line = ""
    file_path = None
    line_number = None

    for i in range(traceback_start + 1, len(lines)):
        line = lines[i]

        # File reference: '  File "/path/to/file.py", line 42, in function_name'
        file_match = re.match(r'\s*File "([^"]+)", line (\d+)', line)
        if file_match:
            file_path = file_match.group(1)
            line_number = int(file_match.group(2))
            stack_trace.append(line)
            continue

        # Error message (last line)
        if line and not line.startswith(' '):
            error_line = line
            break

        if line.strip():
            stack_trace.append(line)

    # Determine error type and suggestions
    error_type = "runtime"
    root_cause = error_line
    suggested_fix = "Fix the error in the indicated file and line"

    if "NameError" in error_line:
        error_type = "name_error"
        root_cause = "Variable or function not defined"
        suggested_fix = "Check spelling and ensure the name is defined before use"
    elif "TypeError" in error_line:
        error_type = "type_error"
        root_cause = "Incorrect type used in operation"
        suggested_fix = "Check the types of variables and function arguments"
    elif "AttributeError" in error_line:
        error_type = "attribute_error"
        root_cause = "Attribute does not exist on object"
        suggested_fix = "Check the object type and available attributes"
    elif "ImportError" in error_line or "ModuleNotFoundError" in error_line:
        error_type = "import"
        root_cause = "Module or package not found"
        suggested_fix = "Check import path and ensure package is installed"

    return ErrorAnalysis(
        error_type=error_type,
        file_path=file_path,
        line_number=line_number,
        error_message=error_line,
        stack_trace=stack_trace,
        root_cause=root_cause,
        suggested_fix=suggested_fix
    )


def _parse_typescript_error(output: str) -> ErrorAnalysis:
    """Parse TypeScript compiler error."""
    # TypeScript errors: "src/file.ts(42,10): error TS2304: Cannot find name 'foo'."

    match = re.search(
        r'([^\s]+\.ts)\((\d+),\d+\): error (TS\d+): (.+)',
        output
    )

    if not match:
        return _generic_error(output)

    file_path = match.group(1)
    line_number = int(match.group(2))
    error_code = match.group(3)
    error_message = match.group(4)

    # Categorize TypeScript errors
    error_type = "typescript"
    root_cause = error_message
    suggested_fix = "Fix the TypeScript error"

    if "Cannot find name" in error_message:
        error_type = "typescript_name"
        root_cause = "Variable, function, or type not found"
        suggested_fix = "Check spelling, imports, and type definitions"
    elif "Type" in error_message and "is not assignable to type" in error_message:
        error_type = "typescript_type"
        root_cause = "Type mismatch"
        suggested_fix = "Ensure types are compatible or add type assertion"

    return ErrorAnalysis(
        error_type=error_type,
        file_path=file_path,
        line_number=line_number,
        error_message=f"{error_code}: {error_message}",
        stack_trace=[],
        root_cause=root_cause,
        suggested_fix=suggested_fix
    )


def _parse_test_failure(output: str) -> ErrorAnalysis:
    """Parse test failure output."""
    # Look for test failure patterns

    # pytest: "FAILED tests/test_file.py::test_function - AssertionError: ..."
    pytest_match = re.search(
        r'FAILED ([^\s]+)::([^\s]+) - (.+)',
        output
    )

    if pytest_match:
        file_path = pytest_match.group(1)
        test_name = pytest_match.group(2)
        error_msg = pytest_match.group(3)

        return ErrorAnalysis(
            error_type="test_failure",
            file_path=file_path,
            line_number=None,
            error_message=f"Test '{test_name}' failed: {error_msg}",
            stack_trace=[],
            root_cause="Test assertion failed",
            suggested_fix="Review the test expectations and fix the implementation"
        )

    return _generic_error(output)


def _parse_import_error(output: str) -> ErrorAnalysis:
    """Parse import/module error."""
    # Python: "ModuleNotFoundError: No module named 'foo'"
    # Node: "Cannot find module 'foo'"

    module_match = re.search(
        r"(?:ModuleNotFoundError|Cannot find module)[:\s]+['\"]([^'\"]+)['\"]",
        output
    )

    module_name = module_match.group(1) if module_match else "unknown"

    return ErrorAnalysis(
        error_type="import",
        file_path=None,
        line_number=None,
        error_message=f"Module '{module_name}' not found",
        stack_trace=[],
        root_cause=f"Package '{module_name}' is not installed or import path is incorrect",
        suggested_fix="Install the package or fix the import path. Use codebase-retrieval to find correct import patterns."
    )


def _parse_syntax_error(output: str) -> ErrorAnalysis:
    """Parse syntax error."""
    return ErrorAnalysis(
        error_type="syntax",
        file_path=None,
        line_number=None,
        error_message=_extract_last_n_chars(output, 300),
        stack_trace=[],
        root_cause="Syntax error in code",
        suggested_fix="Review the syntax error message and fix the code"
    )


def _generic_error(output: str) -> ErrorAnalysis:
    """Create generic error analysis."""
    return ErrorAnalysis(
        error_type="unknown",
        file_path=None,
        line_number=None,
        error_message=_extract_last_n_chars(output, 500),
        stack_trace=[],
        root_cause="Unable to determine root cause",
        suggested_fix="Review the error output and try again"
    )


def _extract_last_n_chars(text: str, n: int) -> str:
    """Extract last N characters, adding ellipsis if truncated."""
    if len(text) <= n:
        return text
    return "...\n" + text[-n:]


__all__ = [
    "ErrorAnalysis",
    "analyze_error_output",
]

