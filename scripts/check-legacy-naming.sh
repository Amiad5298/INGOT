#!/usr/bin/env bash
# Guard script to prevent re-introduction of legacy AGENT_PLATFORM naming.
# Used by both CI and pre-commit. See AMI-66.

set -euo pipefail

echo "Checking for forbidden AGENT_PLATFORM pattern in spec/ and tests/..."
if grep -r -i -n "agent_platform" --include="*.py" spec/ tests/ 2>/dev/null; then
  echo ""
  echo "ERROR: Found legacy AGENT_PLATFORM naming. Use AI_BACKEND instead. See AMI-66."
  exit 1
fi
echo "No legacy naming patterns found."
