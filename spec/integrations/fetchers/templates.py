"""Shared prompt templates for MCP-mediated ticket fetching.

These templates are used by both AuggieMediatedFetcher and
ClaudeMediatedFetcher to request structured JSON responses from
AI backends via their MCP tool integrations.

Templates use {{}} for literal braces in f-string-style templates
and {ticket_id} as the only interpolation placeholder.
"""

from __future__ import annotations

from spec.integrations.providers.base import Platform

# Platforms supported by AI backend MCP integrations
SUPPORTED_PLATFORMS = {Platform.JIRA, Platform.LINEAR, Platform.GITHUB}

# Required fields per platform for validation
# These are the minimum fields that must be present for normalization
REQUIRED_FIELDS: dict[Platform, set[str]] = {
    Platform.JIRA: {"key", "summary"},
    Platform.LINEAR: {"identifier", "title"},
    Platform.GITHUB: {"number", "title"},
}

# Platform-specific prompt templates for structured JSON responses
# NOTE: Templates use valid JSON examples only - no "or null" syntax that could be
# output literally. Instead, we describe optional fields in comments.
PLATFORM_PROMPT_TEMPLATES: dict[Platform, str] = {
    Platform.JIRA: """Use your Jira tool to fetch issue {ticket_id}.

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields marked (optional) can be null if not available.

{{
  "key": "PROJ-123",
  "summary": "ticket title",
  "description": "full description text",
  "status": "Open",
  "issuetype": "Bug",
  "assignee": null,
  "labels": ["label1", "label2"],
  "created": "2024-01-15T10:30:00Z",
  "updated": "2024-01-16T14:20:00Z",
  "priority": "High",
  "project": {{"key": "PROJ", "name": "Project Name"}}
}}""",
    Platform.LINEAR: """Use your Linear tool to fetch issue {ticket_id}.

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields can be null if not available.

{{
  "identifier": "TEAM-123",
  "title": "issue title",
  "description": "full description text",
  "state": {{"name": "Todo"}},
  "assignee": null,
  "labels": {{"nodes": [{{"name": "label1"}}]}},
  "createdAt": "2024-01-15T10:30:00Z",
  "updatedAt": "2024-01-16T14:20:00Z",
  "priority": 2,
  "team": {{"key": "TEAM"}},
  "url": "https://linear.app/team/issue/TEAM-123"
}}""",
    Platform.GITHUB: """Use your GitHub API tool to fetch issue or PR {ticket_id}.

The ticket_id format is "owner/repo#number" (e.g., "microsoft/vscode#12345").

Return ONLY a valid JSON object with these fields (no markdown, no explanation).
Fields can be null if not available.

{{
  "number": 123,
  "title": "issue/PR title",
  "body": "full description text",
  "state": "open",
  "user": {{"login": "username"}},
  "labels": [{{"name": "label1"}}],
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-16T14:20:00Z",
  "html_url": "https://github.com/owner/repo/issues/123",
  "milestone": null,
  "assignee": null
}}""",
}
