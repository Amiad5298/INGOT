"""Deterministic post-processor that auto-corrects plan validation errors.

PlanFixer resolves FileExistsValidator errors by:
1. Searching the FileIndex for the correct path (fuzzy match), or
2. Injecting ``<!-- UNVERIFIED -->`` markers when no match is found.

This eliminates false-positive errors that would otherwise trigger
retries or user prompts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ingot.validation.base import ValidationReport, ValidationSeverity

if TYPE_CHECKING:
    from ingot.discovery.file_index import FileIndex

# Match the error message format from FileExistsValidator
_FILE_NOT_FOUND_RE = re.compile(r"^File not found: `(.+)`$")


class PlanFixer:
    """Deterministic post-processor that auto-corrects plan validation errors.

    Only fixes ``FileExistsValidator`` errors — these are the common
    false positives when the AI planner omits ``<!-- NEW_FILE -->`` or
    ``<!-- UNVERIFIED -->`` markers. Other validators (e.g.
    ``RequiredSectionsValidator``) produce real issues that require AI retry.

    When a :class:`FileIndex` is provided, attempts to fuzzy-match the
    missing path before falling back to UNVERIFIED stamping.

    Args:
        file_index: Optional FileIndex for fuzzy path correction.
    """

    def __init__(self, file_index: FileIndex | None = None) -> None:
        self._file_index = file_index

    def fix(self, content: str, report: ValidationReport) -> tuple[str, list[str]]:
        """Apply deterministic fixes to plan content.

        Args:
            content: Raw plan text.
            report: Validation report with findings to fix.

        Returns:
            Tuple of (fixed_content, list_of_fix_descriptions).
            If no fixes are applied, ``content`` is returned unchanged.
        """
        lines = content.split("\n")
        fixes: list[str] = []

        for finding in report.findings:
            if finding.severity != ValidationSeverity.ERROR:
                continue
            if finding.validator_name != "File Exists":
                continue
            if finding.line_number is None:
                continue

            bad_path = finding.metadata.get("path")
            if not bad_path:
                path_match = _FILE_NOT_FOUND_RE.match(finding.message)
                if not path_match:
                    continue
                bad_path = path_match.group(1)
            idx = finding.line_number - 1  # 0-based
            if idx < 0 or idx >= len(lines):
                continue

            line = lines[idx]

            # Idempotent: skip if already marked
            if "<!-- UNVERIFIED" in line or "<!-- NEW_FILE" in line:
                continue

            # Strategy 1: Try fuzzy-find via FileIndex
            if self._file_index is not None:
                # Extract just the filename part for fuzzy matching
                filename = bad_path.rsplit("/", 1)[-1] if "/" in bad_path else bad_path
                corrected = self._file_index.fuzzy_find(filename)
                if corrected is not None:
                    corrected_str = str(corrected)
                    # Replace the bad path with the corrected one inline
                    lines[idx] = line.replace(bad_path, corrected_str, 1)
                    fixes.append(
                        f"Corrected `{bad_path}` → `{corrected_str}` (line {finding.line_number})"
                    )
                    continue

            # Strategy 2: Fall back to UNVERIFIED stamping
            lines[idx] = f"{line} <!-- UNVERIFIED: auto-flagged, file not in repo -->"
            fixes.append(f"Marked `{bad_path}` as UNVERIFIED (line {finding.line_number})")

        if not fixes:
            return content, fixes
        return "\n".join(lines), fixes


__all__ = ["PlanFixer"]
