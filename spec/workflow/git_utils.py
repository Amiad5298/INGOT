"""Git utilities for Step 3 execution.

This module provides utilities for interacting with git during the
execution phase, including smart diff collection that handles large
changesets appropriately.
"""

import re
import subprocess

from spec.utils.console import print_warning


def parse_stat_total_lines(stat_output: str) -> int:
    """Parse total changed lines from git diff --stat output.

    The stat output ends with a summary line like:
    "10 files changed, 500 insertions(+), 100 deletions(-)"

    Args:
        stat_output: Output from git diff --stat

    Returns:
        Total lines changed (insertions + deletions)
    """
    # Match the summary line at the end of stat output
    # Pattern: "X file(s) changed, Y insertion(s)(+), Z deletion(s)(-)"
    match = re.search(
        r"(\d+)\s+insertions?\(\+\).*?(\d+)\s+deletions?\(-\)",
        stat_output,
    )
    if match:
        return int(match.group(1)) + int(match.group(2))

    # Try matching insertions only
    match = re.search(r"(\d+)\s+insertions?\(\+\)", stat_output)
    if match:
        return int(match.group(1))

    # Try matching deletions only
    match = re.search(r"(\d+)\s+deletions?\(-\)", stat_output)
    if match:
        return int(match.group(1))

    return 0


def parse_stat_file_count(stat_output: str) -> int:
    """Parse number of changed files from git diff --stat output.

    Args:
        stat_output: Output from git diff --stat

    Returns:
        Number of files changed
    """
    match = re.search(r"(\d+)\s+files?\s+changed", stat_output)
    if match:
        return int(match.group(1))
    return 0


def get_smart_diff(max_lines: int = 2000, max_files: int = 20) -> tuple[str, bool, bool]:
    """Get diff output, using --stat only for large changes.

    Implements smart diff strategy to handle large diffs that could
    exceed AI context window limits. For large changes, returns only
    the stat summary and instructs the reviewer to inspect specific
    files as needed.

    Args:
        max_lines: Maximum lines before falling back to stat-only (default: 2000)
        max_files: Maximum files before falling back to stat-only (default: 20)

    Returns:
        Tuple of (diff_output, is_truncated, git_error) where:
        - is_truncated is True if only stat output was returned due to large changeset
        - git_error is True if git command failed (diff may be unreliable)
    """
    # First get stat output to assess change size
    stat_result = subprocess.run(
        ["git", "diff", "--stat"],
        capture_output=True,
        text=True,
    )

    # Check for git errors
    if stat_result.returncode != 0:
        stderr = stat_result.stderr.strip() if stat_result.stderr else "unknown error"
        print_warning(f"Git diff --stat failed (exit code {stat_result.returncode}): {stderr}")
        # Return empty with error flag - caller should warn but continue
        return "", False, True

    stat_output = stat_result.stdout

    if not stat_output.strip():
        # No changes - return empty (not an error, just empty diff)
        return "", False, False

    # Parse stat to get counts
    lines_changed = parse_stat_total_lines(stat_output)
    files_changed = parse_stat_file_count(stat_output)

    # Check if diff is too large
    if lines_changed > max_lines or files_changed > max_files:
        # Return stat-only with instructions
        truncated_output = f"""## Git Diff Summary (Large Changeset)

{stat_output}

**Note**: This changeset is large ({files_changed} files, {lines_changed} lines changed).
To review specific files in detail, use: `git diff -- <file_path>`
Focus on files most critical to the implementation plan."""
        return truncated_output, True, False

    # Small enough for full diff
    full_result = subprocess.run(
        ["git", "diff"],
        capture_output=True,
        text=True,
    )

    # Check for git errors on full diff
    if full_result.returncode != 0:
        stderr = full_result.stderr.strip() if full_result.stderr else "unknown error"
        print_warning(f"Git diff failed (exit code {full_result.returncode}): {stderr}")
        # Fall back to stat output with error flag
        return stat_output, True, True

    return full_result.stdout, False, False


# Backwards-compatible aliases (underscore-prefixed)
_parse_stat_total_lines = parse_stat_total_lines
_parse_stat_file_count = parse_stat_file_count
_get_smart_diff = get_smart_diff


__all__ = [
    "parse_stat_total_lines",
    "parse_stat_file_count",
    "get_smart_diff",
    # Backwards-compatible aliases
    "_parse_stat_total_lines",
    "_parse_stat_file_count",
    "_get_smart_diff",
]

