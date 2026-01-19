# GitHub Issues Integration Specification

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification details the implementation of the GitHub Issues provider for SPECFLOW's platform-agnostic issue tracker integration. GitHub Issues is a widely-used issue tracking system built into GitHub repositories.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Authentication](#2-authentication)
3. [API Endpoints](#3-api-endpoints)
4. [Field Mapping](#4-field-mapping)
5. [URL Patterns](#5-url-patterns)
6. [Implementation Details](#6-implementation-details)
7. [Edge Cases & Limitations](#7-edge-cases--limitations)
8. [Testing Strategy](#8-testing-strategy)

---

## 1. Platform Overview

### 1.1 Service Information

| Property | Value |
|----------|-------|
| Platform Name | GitHub Issues |
| API Type | REST (v3) and GraphQL (v4) |
| Base URL | `https://api.github.com` |
| GraphQL Endpoint | `https://api.github.com/graphql` |
| Documentation | https://docs.github.com/en/rest/issues |
| Rate Limits | 5,000 requests/hour (authenticated) |

### 1.2 Scope

This integration covers:
- ✅ GitHub Issues (standard issues)
- ✅ GitHub Pull Requests (treated as a type of issue)
- ✅ Public and private repositories
- ✅ GitHub.com and GitHub Enterprise Server

---

## 2. Authentication

### 2.1 Supported Methods

| Method | Use Case | Recommended |
|--------|----------|-------------|
| Personal Access Token (PAT) | Individual users, CLI tools | ✅ Yes |
| GitHub App Installation Token | Org-wide automation | For enterprise |
| OAuth Token | Web applications | Not for CLI |

### 2.2 Required Scopes

For PAT (classic):
- `repo` - Full access to private repositories
- `read:org` - Read org membership (for org-owned repos)

For Fine-grained PAT:
- Repository access: Select specific repos or all repos
- Permissions: `Issues: Read-only` (minimum), `Pull requests: Read-only`

### 2.3 Configuration

```bash
# ~/.specflow-config
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_DEFAULT_OWNER=myorg           # Optional: default org/user
GITHUB_DEFAULT_REPO=myrepo           # Optional: default repository
GITHUB_ENTERPRISE_URL=               # Optional: for GHE (e.g., https://github.mycompany.com)
```

### 2.4 Authentication Header

```http
Authorization: Bearer ghp_xxxxxxxxxxxx
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
```

---

## 3. API Endpoints

### 3.1 Fetch Single Issue

**REST API v3:**

```http
GET /repos/{owner}/{repo}/issues/{issue_number}
```

**Example Request:**
```bash
curl -H "Authorization: Bearer $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/octocat/Hello-World/issues/42
```

**Example Response:**
```json
{
  "id": 1,
  "node_id": "MDU6SXNzdWUx",
  "url": "https://api.github.com/repos/octocat/Hello-World/issues/42",
  "html_url": "https://github.com/octocat/Hello-World/issues/42",
  "number": 42,
  "state": "open",
  "title": "Found a bug",
  "body": "I'm having a problem with this.",
  "user": {
    "login": "octocat",
    "id": 1
  },
  "labels": [
    {"name": "bug", "color": "f29513"}
  ],
  "assignee": {
    "login": "octocat"
  },
  "assignees": [
    {"login": "octocat"},
    {"login": "hubot"}
  ],
  "milestone": {
    "title": "v1.0"
  },
  "created_at": "2011-04-22T13:33:48Z",
  "updated_at": "2011-04-22T13:33:48Z",
  "closed_at": null,
  "pull_request": null
}
```

### 3.2 Check if Issue or PR

Issues and PRs share the same number space. To distinguish:
- If `pull_request` field exists → it's a Pull Request
- If `pull_request` is `null` → it's an Issue

### 3.3 GraphQL Alternative (Optional)

For richer data in single request:

```graphql
query GetIssue($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    issue(number: $number) {
      id
      number
      title
      body
      state
      createdAt
      updatedAt
      author { login }
      assignees(first: 10) { nodes { login } }
      labels(first: 10) { nodes { name } }
    }
  }
}
```

### 3.4 Connection Check Endpoint

```http
GET /user
```

Returns authenticated user info. Use for connection verification.

---

## 4. Field Mapping

### 4.1 GenericTicket Mapping Table

| GenericTicket Field | GitHub API Field | Transform |
|---------------------|------------------|-----------|
| `id` | `"{owner}/{repo}#{number}"` | Composite key |
| `platform` | - | `Platform.GITHUB` (constant) |
| `url` | `html_url` | Direct |
| `title` | `title` | Direct |
| `description` | `body` | Direct (may be null) |
| `status` | `state` | Map: see 4.2 |
| `type` | `labels[*].name` | Map: see 4.4 |
| `assignee` | `assignee.login` or `assignees[0].login` | First assignee |
| `labels` | `labels[*].name` | Extract names |
| `created_at` | `created_at` | Parse ISO 8601 |
| `updated_at` | `updated_at` | Parse ISO 8601 |
| `branch_summary` | Generated from `title` | Sanitize |
| `platform_metadata.is_pull_request` | `pull_request != null` | Boolean |
| `platform_metadata.milestone` | `milestone.title` | If exists |
| `platform_metadata.repository` | `"{owner}/{repo}"` | Computed |

### 4.2 Status Mapping

| GitHub State | GenericTicket Status |
|--------------|---------------------|
| `open` | `TicketStatus.OPEN` |
| `closed` (not merged) | `TicketStatus.CLOSED` |
| `closed` (merged, PR only) | `TicketStatus.DONE` |

**Note:** GitHub Issues only have `open` or `closed`. For more granular status, check labels like `in-progress`, `review`, etc.

### 4.3 Label-Based Status Enhancement

Optionally parse common labels to enrich status:

```python
LABEL_STATUS_MAP = {
    "in progress": TicketStatus.IN_PROGRESS,
    "in-progress": TicketStatus.IN_PROGRESS,
    "wip": TicketStatus.IN_PROGRESS,
    "review": TicketStatus.REVIEW,
    "needs review": TicketStatus.REVIEW,
    "done": TicketStatus.DONE,
}
```

### 4.4 Type Mapping

GitHub Issues don't have a native "type" field. Type is inferred from labels:

**Type Mapping Strategy:**

```python
TYPE_KEYWORDS = {
    TicketType.BUG: ["bug", "defect", "fix", "error", "crash", "regression"],
    TicketType.FEATURE: ["feature", "enhancement", "feat", "story", "request"],
    TicketType.TASK: ["task", "chore", "todo", "housekeeping"],
    TicketType.MAINTENANCE: ["maintenance", "tech-debt", "refactor", "cleanup", "infrastructure", "deps", "dependencies"],
}

def map_type(labels: list[str]) -> TicketType:
    """Map GitHub labels to TicketType.

    Args:
        labels: List of label names from the issue

    Returns:
        Matched TicketType or UNKNOWN
    """
    for label in labels:
        label_lower = label.lower().strip()
        for ticket_type, keywords in TYPE_KEYWORDS.items():
            if any(kw in label_lower for kw in keywords):
                return ticket_type

    return TicketType.UNKNOWN
```

**Common GitHub Label Mappings:**

| GitHub Label | TicketType |
|--------------|------------|
| `bug` | `TicketType.BUG` |
| `type: bug` | `TicketType.BUG` |
| `kind/bug` | `TicketType.BUG` |
| `enhancement` | `TicketType.FEATURE` |
| `feature` | `TicketType.FEATURE` |
| `type: feature` | `TicketType.FEATURE` |
| `chore` | `TicketType.TASK` |
| `maintenance` | `TicketType.MAINTENANCE` |
| `tech-debt` | `TicketType.MAINTENANCE` |
| `dependencies` | `TicketType.MAINTENANCE` |

---

## 5. URL Patterns

### 5.1 Supported URL Formats

| Pattern | Example | Regex |
|---------|---------|-------|
| Issue URL | `https://github.com/owner/repo/issues/123` | `https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)` |
| PR URL | `https://github.com/owner/repo/pull/123` | `https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)` |
| Short Reference | `owner/repo#123` | `^([^/]+)/([^/]+)#(\d+)$` |
| GHE Issue | `https://github.company.com/owner/repo/issues/123` | Custom domain support |

### 5.2 ID Normalization

Internal ticket ID format: `{owner}/{repo}#{number}`

Examples:
- `octocat/Hello-World#42`
- `myorg/backend#1234`

---

## 6. Implementation Details

### 6.1 Provider Class

```python
from specflow.integrations.providers.base import (
    IssueTrackerProvider,
    GenericTicket,
    Platform,
    TicketStatus,
)
from specflow.integrations.providers.registry import ProviderRegistry
from specflow.integrations.providers.cache import cached_fetch

import requests
from datetime import datetime, timedelta
import re

@ProviderRegistry.register
class GitHubProvider(IssueTrackerProvider):
    """GitHub Issues provider."""

    PLATFORM = Platform.GITHUB
    API_BASE = "https://api.github.com"

    def __init__(self):
        self._token = None
        self._session = None

    @property
    def platform(self) -> Platform:
        return Platform.GITHUB

    @property
    def name(self) -> str:
        return "GitHub Issues"

    def _get_session(self) -> requests.Session:
        """Get configured requests session."""
        if self._session is None:
            from specflow.config.manager import ConfigManager
            config = ConfigManager()
            config.load()

            self._token = config.get("GITHUB_TOKEN", "")
            if not self._token:
                raise AuthenticationError("GITHUB_TOKEN not configured")

            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            })
        return self._session

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a GitHub issue reference."""
        patterns = [
            r"https?://github\.com/[^/]+/[^/]+/(issues|pull)/\d+",
            r"^[^/]+/[^/]+#\d+$",
        ]
        return any(re.match(p, input_str.strip()) for p in patterns)

    def parse_input(self, input_str: str) -> str:
        """Parse GitHub issue URL or reference."""
        input_str = input_str.strip()

        # URL pattern
        url_match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)",
            input_str
        )
        if url_match:
            owner, repo, _, number = url_match.groups()
            return f"{owner}/{repo}#{number}"

        # Short reference
        ref_match = re.match(r"^([^/]+)/([^/]+)#(\d+)$", input_str)
        if ref_match:
            owner, repo, number = ref_match.groups()
            return f"{owner}/{repo}#{number}"

        raise ValueError(f"Invalid GitHub issue reference: {input_str}")

    @cached_fetch(ttl=timedelta(hours=1))
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch issue from GitHub API."""
        # Parse ticket_id: "owner/repo#123"
        match = re.match(r"^([^/]+)/([^/]+)#(\d+)$", ticket_id)
        if not match:
            raise ValueError(f"Invalid ticket ID format: {ticket_id}")

        owner, repo, number = match.groups()

        session = self._get_session()
        response = session.get(f"{self.API_BASE}/repos/{owner}/{repo}/issues/{number}")

        if response.status_code == 404:
            raise TicketNotFoundError(
                ticket_id=ticket_id,
                platform=self.name,
            )
        elif response.status_code == 401:
            raise AuthenticationError("GitHub authentication failed")
        elif response.status_code == 403:
            if "rate limit" in response.text.lower():
                retry_after = response.headers.get("Retry-After")
                raise RateLimitError(int(retry_after) if retry_after else None)
            raise AuthenticationError("Access denied to repository")

        response.raise_for_status()
        data = response.json()

        return self._map_to_generic(data, owner, repo)

    def _map_to_generic(self, data: dict, owner: str, repo: str) -> GenericTicket:
        """Map GitHub API response to GenericTicket."""
        # Determine status
        status = TicketStatus.OPEN
        if data["state"] == "closed":
            # Check if PR was merged
            if data.get("pull_request") and data.get("merged_at"):
                status = TicketStatus.DONE
            else:
                status = TicketStatus.CLOSED

        # Check labels for status hints
        labels = [l["name"] for l in data.get("labels", [])]
        for label in labels:
            label_lower = label.lower()
            if label_lower in ("in progress", "in-progress", "wip"):
                status = TicketStatus.IN_PROGRESS
                break
            elif label_lower in ("review", "needs review"):
                status = TicketStatus.REVIEW
                break

        # Get assignee
        assignee = None
        if data.get("assignee"):
            assignee = data["assignee"]["login"]
        elif data.get("assignees"):
            assignee = data["assignees"][0]["login"]

        return GenericTicket(
            id=f"{owner}/{repo}#{data['number']}",
            platform=Platform.GITHUB,
            url=data["html_url"],
            title=data["title"],
            description=data.get("body") or "",
            status=status,
            assignee=assignee,
            labels=labels,
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
            platform_metadata={
                "is_pull_request": data.get("pull_request") is not None,
                "repository": f"{owner}/{repo}",
                "milestone": data.get("milestone", {}).get("title"),
                "author": data.get("user", {}).get("login"),
            }
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify GitHub API access."""
        try:
            session = self._get_session()
            response = session.get(f"{self.API_BASE}/user")
            if response.status_code == 200:
                user = response.json()["login"]
                return True, f"Connected as {user}"
            return False, f"API error: {response.status_code}"
        except AuthenticationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection failed: {e}"
```


---

## 7. Edge Cases & Limitations

### 7.1 Rate Limiting

| Limit Type | Value | Handling |
|------------|-------|----------|
| Authenticated requests | 5,000/hour | Check `X-RateLimit-Remaining` header |
| Search API | 30/minute | Not used for single issue fetch |
| Unauthenticated | 60/hour | Not supported |

**Rate Limit Headers:**
```http
X-RateLimit-Limit: 5000
X-RateLimit-Remaining: 4987
X-RateLimit-Reset: 1644518400
```

**Handling Strategy:**
1. Check `Remaining` before requests
2. If 403 with rate limit message, raise `RateLimitError`
3. Use `Reset` timestamp for retry delay

### 7.2 Private Repositories

- Requires `repo` scope on PAT
- Returns 404 (not 403) if token lacks access
- Handle 404 as "not found or no access"

### 7.3 GitHub Enterprise

```python
def _get_api_base(self) -> str:
    """Get API base URL, supporting GHE."""
    from specflow.config.manager import ConfigManager
    config = ConfigManager()
    config.load()

    ghe_url = config.get("GITHUB_ENTERPRISE_URL", "")
    if ghe_url:
        return f"{ghe_url.rstrip('/')}/api/v3"
    return "https://api.github.com"
```

### 7.4 Large Issue Bodies

- Issue body can be up to 65,536 characters
- May contain markdown, images, code blocks
- Truncate `description` field for display if needed

### 7.5 Draft PRs

- Draft PRs have `draft: true` in response
- Store in `platform_metadata.is_draft`

### 7.6 Locked Issues

- Locked issues have `locked: true`
- Include in metadata: `platform_metadata.is_locked`

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
class TestGitHubProvider:
    """Unit tests for GitHubProvider."""

    def test_can_handle_issue_url(self):
        provider = GitHubProvider()
        assert provider.can_handle("https://github.com/owner/repo/issues/123")

    def test_can_handle_pr_url(self):
        provider = GitHubProvider()
        assert provider.can_handle("https://github.com/owner/repo/pull/456")

    def test_can_handle_short_ref(self):
        provider = GitHubProvider()
        assert provider.can_handle("owner/repo#789")

    def test_cannot_handle_jira(self):
        provider = GitHubProvider()
        assert not provider.can_handle("PROJECT-123")

    def test_parse_input_url(self):
        provider = GitHubProvider()
        result = provider.parse_input("https://github.com/octocat/Hello-World/issues/42")
        assert result == "octocat/Hello-World#42"

    def test_parse_input_short_ref(self):
        provider = GitHubProvider()
        result = provider.parse_input("octocat/repo#100")
        assert result == "octocat/repo#100"

    @pytest.fixture
    def mock_api_response(self):
        return {
            "number": 42,
            "title": "Test Issue",
            "body": "Description here",
            "state": "open",
            "html_url": "https://github.com/owner/repo/issues/42",
            "labels": [{"name": "bug"}],
            "assignee": {"login": "developer"},
            "created_at": "2024-01-15T10:30:00Z",
            "updated_at": "2024-01-16T14:00:00Z",
            "pull_request": None,
        }

    def test_fetch_ticket_maps_correctly(self, mock_api_response, mocker):
        provider = GitHubProvider()
        mocker.patch.object(provider, "_get_session")
        provider._get_session().get.return_value.status_code = 200
        provider._get_session().get.return_value.json.return_value = mock_api_response

        ticket = provider.fetch_ticket("owner/repo#42")

        assert ticket.id == "owner/repo#42"
        assert ticket.platform == Platform.GITHUB
        assert ticket.title == "Test Issue"
        assert ticket.status == TicketStatus.OPEN
        assert ticket.assignee == "developer"
        assert "bug" in ticket.labels

    def test_fetch_ticket_handles_404(self, mocker):
        provider = GitHubProvider()
        mocker.patch.object(provider, "_get_session")
        provider._get_session().get.return_value.status_code = 404

        with pytest.raises(TicketNotFoundError):
            provider.fetch_ticket("owner/repo#999")

    def test_check_connection_success(self, mocker):
        provider = GitHubProvider()
        mocker.patch.object(provider, "_get_session")
        provider._get_session().get.return_value.status_code = 200
        provider._get_session().get.return_value.json.return_value = {"login": "testuser"}

        success, message = provider.check_connection()
        assert success
        assert "testuser" in message
```

### 8.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("GITHUB_TOKEN"), reason="No GitHub token")
class TestGitHubProviderIntegration:
    """Integration tests against real GitHub API."""

    def test_fetch_real_issue(self):
        provider = GitHubProvider()
        # Use a well-known public issue
        ticket = provider.fetch_ticket("octocat/Hello-World#1")
        assert ticket.title  # Has a title
        assert ticket.platform == Platform.GITHUB

    def test_connection_check(self):
        provider = GitHubProvider()
        success, _ = provider.check_connection()
        assert success
```

---

## Appendix A: API Response Examples

### A.1 Closed Issue

```json
{
  "state": "closed",
  "closed_at": "2024-01-20T15:00:00Z",
  "state_reason": "completed"
}
```

### A.2 Pull Request (via Issues endpoint)

```json
{
  "pull_request": {
    "url": "https://api.github.com/repos/owner/repo/pulls/42",
    "html_url": "https://github.com/owner/repo/pull/42",
    "merged_at": null
  }
}
```

---

*End of GitHub Integration Specification*

