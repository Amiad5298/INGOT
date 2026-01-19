# Linear Integration Specification

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification details the implementation of the Linear provider for SPECFLOW's platform-agnostic issue tracker integration. Linear is a modern project management tool popular among software development teams for its speed, simplicity, and developer-focused design.

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
| Platform Name | Linear |
| API Type | GraphQL only |
| API Endpoint | `https://api.linear.app/graphql` |
| Documentation | https://developers.linear.app/docs |
| Rate Limits | 1,500 requests/hour (API key), varies by complexity |

### 1.2 Key Concepts

| Linear Term | Generic Equivalent |
|-------------|-------------------|
| Issue | Ticket |
| Team | Project/Board |
| Workflow State | Status |
| Assignee | Assignee |
| Label | Label/Tag |
| Cycle | Sprint/Iteration |
| Project | Epic/Initiative |

### 1.3 Scope

This integration covers:
- ✅ Issues (main focus)
- ✅ Sub-issues
- ✅ Labels and workflow states
- ❌ Projects (future enhancement)
- ❌ Cycles (future enhancement)

---

## 2. Authentication

### 2.1 Supported Methods

| Method | Use Case | Recommended |
|--------|----------|-------------|
| Personal API Key | Individual users, CLI tools | ✅ Yes |
| OAuth 2.0 | Web applications | Not for CLI |

### 2.2 Obtaining API Key

1. Go to Linear Settings → API
2. Click "Create new API key"
3. Name it (e.g., "SPECFLOW CLI")
4. Copy the key (starts with `lin_api_`)

### 2.3 Configuration

```bash
# ~/.specflow-config
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
LINEAR_DEFAULT_TEAM=ENG              # Optional: team key for ambiguous IDs
```

### 2.4 Authentication Header

```http
Authorization: lin_api_xxxxxxxxxxxx
Content-Type: application/json
```

---

## 3. API Endpoints

### 3.1 GraphQL Endpoint

All Linear API access is through a single GraphQL endpoint:

```
POST https://api.linear.app/graphql
```

### 3.2 Fetch Issue by ID (Identifier)

Linear issues have identifiers like `ENG-123`. The query:

```graphql
query GetIssue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    url
    state {
      id
      name
      type
    }
    assignee {
      id
      name
      email
    }
    labels {
      nodes {
        id
        name
        color
      }
    }
    createdAt
    updatedAt
    priority
    priorityLabel
    team {
      id
      key
      name
    }
    parent {
      id
      identifier
    }
  }
}
```

**Note:** The `id` parameter accepts either:
- The internal UUID: `a1b2c3d4-...`
- The identifier: `ENG-123`

### 3.3 Example API Call

```bash
curl -X POST https://api.linear.app/graphql \
  -H "Authorization: lin_api_xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query { issue(id: \"ENG-123\") { id identifier title description state { name type } } }"
  }'
```

### 3.4 Example Response

```json
{
  "data": {
    "issue": {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "identifier": "ENG-123",
      "title": "Implement user authentication",
      "description": "Add OAuth2 login flow with Google and GitHub providers.",
      "url": "https://linear.app/myteam/issue/ENG-123",
      "state": {
        "id": "state-id-123",
        "name": "In Progress",
        "type": "started"
      },
      "assignee": {
        "id": "user-id-456",
        "name": "Jane Developer",
        "email": "jane@company.com"
      },
      "labels": {
        "nodes": [
          {"id": "label-1", "name": "feature", "color": "#5e6ad2"},
          {"id": "label-2", "name": "backend", "color": "#26b5ce"}
        ]
      },
      "createdAt": "2024-01-15T10:30:00.000Z",
      "updatedAt": "2024-01-18T14:20:00.000Z",
      "priority": 2,
      "priorityLabel": "High",
      "team": {
        "id": "team-id-789",
        "key": "ENG",
        "name": "Engineering"
      }
    }
  }
}
```

### 3.5 Connection Check Query

```graphql
query Viewer {
  viewer {
    id
    name
    email
  }
}
```

---

## 4. Field Mapping

### 4.1 GenericTicket Mapping Table

| GenericTicket Field | Linear API Field | Transform |
|---------------------|------------------|-----------|
| `id` | `identifier` | Direct (e.g., "ENG-123") |
| `platform` | - | `Platform.LINEAR` (constant) |
| `url` | `url` | Direct |
| `title` | `title` | Direct |
| `description` | `description` | Direct (markdown) |
| `status` | `state.type` | Map: see 4.2 |
| `type` | `labels.nodes[*].name` | Map: see 4.4 |
| `assignee` | `assignee.name` or `assignee.email` | Prefer name |
| `labels` | `labels.nodes[*].name` | Extract names |
| `created_at` | `createdAt` | Parse ISO 8601 |
| `updated_at` | `updatedAt` | Parse ISO 8601 |
| `branch_summary` | Generated from `title` | Sanitize |
| `platform_metadata.team_key` | `team.key` | For context |
| `platform_metadata.priority` | `priorityLabel` | Human-readable |
| `platform_metadata.parent_id` | `parent.identifier` | If sub-issue |

### 4.2 Status Mapping

Linear has workflow states with a `type` field:

| Linear State Type | GenericTicket Status |
|-------------------|---------------------|
| `backlog` | `TicketStatus.OPEN` |
| `unstarted` | `TicketStatus.OPEN` |
| `started` | `TicketStatus.IN_PROGRESS` |
| `completed` | `TicketStatus.DONE` |
| `canceled` | `TicketStatus.CLOSED` |

**Note:** Linear state names are customizable per team. Use `state.type` for reliable mapping.

### 4.3 Priority Levels

| Priority Value | Priority Label |
|----------------|---------------|
| 0 | No priority |
| 1 | Urgent |
| 2 | High |
| 3 | Medium |
| 4 | Low |

### 4.4 Type Mapping

Linear uses labels for categorization. Type is inferred from label names:

**Type Mapping Strategy:**

```python
TYPE_KEYWORDS = {
    TicketType.BUG: ["bug", "defect", "fix", "error", "crash", "regression"],
    TicketType.FEATURE: ["feature", "enhancement", "story", "improvement"],
    TicketType.TASK: ["task", "chore", "todo", "spike"],
    TicketType.MAINTENANCE: ["maintenance", "tech-debt", "refactor", "cleanup", "infrastructure"],
}

def map_type(labels: list[str]) -> TicketType:
    """Map Linear labels to TicketType.

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

**Common Linear Label Mappings:**

| Linear Label | TicketType |
|--------------|------------|
| `Bug` | `TicketType.BUG` |
| `bug` | `TicketType.BUG` |
| `Feature` | `TicketType.FEATURE` |
| `feature` | `TicketType.FEATURE` |
| `Improvement` | `TicketType.FEATURE` |
| `Task` | `TicketType.TASK` |
| `Chore` | `TicketType.TASK` |
| `Tech Debt` | `TicketType.MAINTENANCE` |
| `Infrastructure` | `TicketType.MAINTENANCE` |

---

## 5. URL Patterns

### 5.1 Supported URL Formats

| Pattern | Example | Regex |
|---------|---------|-------|
| Issue URL | `https://linear.app/team/issue/ENG-123` | `https?://linear\.app/([^/]+)/issue/([A-Z]+-\d+)` |
| Issue URL with title | `https://linear.app/team/issue/ENG-123/title-slug` | Same, ignore slug |
| Identifier only | `ENG-123` | `^([A-Z]+-\d+)$` |

### 5.2 Disambiguation

Linear identifiers look like Jira IDs (`ABC-123`). Resolution strategy:

1. If URL contains `linear.app` → Linear
2. If URL contains `atlassian.net` or `/browse/` → Jira
3. If identifier only:
   - Check configured `DEFAULT_PLATFORM`
   - Or prompt user to specify platform

### 5.3 ID Normalization

Internal ticket ID format: `{identifier}` (e.g., `ENG-123`)

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
from specflow.integrations.providers.exceptions import (
    AuthenticationError,
    IssueTrackerError,
    TicketNotFoundError,
    RateLimitError,
)

import requests
from datetime import datetime, timedelta
import re

@ProviderRegistry.register
class LinearProvider(IssueTrackerProvider):
    """Linear issue tracker provider."""

    PLATFORM = Platform.LINEAR
    API_ENDPOINT = "https://api.linear.app/graphql"

    # GraphQL query for fetching issue
    ISSUE_QUERY = """
    query GetIssue($id: String!) {
      issue(id: $id) {
        id
        identifier
        title
        description
        url
        state {
          name
          type
        }
        assignee {
          name
          email
        }
        labels {
          nodes {
            name
          }
        }
        createdAt
        updatedAt
        priority
        priorityLabel
        team {
          key
          name
        }
        parent {
          identifier
        }
      }
    }
    """

    # State type to status mapping
    STATE_TYPE_MAP = {
        "backlog": TicketStatus.OPEN,
        "unstarted": TicketStatus.OPEN,
        "started": TicketStatus.IN_PROGRESS,
        "completed": TicketStatus.DONE,
        "canceled": TicketStatus.CLOSED,
    }

    def __init__(self):
        self._api_key = None
        self._session = None

    @property
    def platform(self) -> Platform:
        return Platform.LINEAR

    @property
    def name(self) -> str:
        return "Linear"

    def _get_session(self) -> requests.Session:
        """Get configured requests session."""
        if self._session is None:
            from specflow.config.manager import ConfigManager
            config = ConfigManager()
            config.load()

            self._api_key = config.get("LINEAR_API_KEY", "")
            if not self._api_key:
                raise AuthenticationError("LINEAR_API_KEY not configured")

            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": self._api_key,
                "Content-Type": "application/json",
            })
        return self._session

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a Linear issue reference."""
        patterns = [
            r"https?://linear\.app/[^/]+/issue/[A-Z]+-\d+",
            # Note: ABC-123 pattern is ambiguous with Jira
            # Only match if explicitly Linear (URL) or configured as default
        ]
        return any(re.match(p, input_str.strip()) for p in patterns)

    def parse_input(self, input_str: str) -> str:
        """Parse Linear issue URL or identifier."""
        input_str = input_str.strip()

        # URL pattern
        url_match = re.match(
            r"https?://linear\.app/[^/]+/issue/([A-Z]+-\d+)",
            input_str
        )
        if url_match:
            return url_match.group(1)

        # Identifier pattern (if we got here, it's confirmed Linear)
        id_match = re.match(r"^([A-Z]+-\d+)$", input_str, re.IGNORECASE)
        if id_match:
            return id_match.group(1).upper()

        raise ValueError(f"Invalid Linear issue reference: {input_str}")

    def _execute_query(self, query: str, variables: dict) -> dict:
        """Execute GraphQL query."""
        session = self._get_session()

        response = session.post(
            self.API_ENDPOINT,
            json={"query": query, "variables": variables}
        )

        if response.status_code == 401:
            raise AuthenticationError("Linear authentication failed - invalid API key")
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise RateLimitError(int(retry_after))

        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            error_msg = result["errors"][0].get("message", "Unknown GraphQL error")
            if "not found" in error_msg.lower():
                ticket_id = variables.get("id", str(variables))
                raise TicketNotFoundError(
                    ticket_id=ticket_id,
                    message=f"Issue not found: {error_msg}",
                    platform=self.name,
                )
            raise IssueTrackerError(
                message=f"Linear API error: {error_msg}",
                platform=self.name,
            )

        return result["data"]

    @cached_fetch(ttl=timedelta(hours=1))
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch issue from Linear API."""
        data = self._execute_query(self.ISSUE_QUERY, {"id": ticket_id})

        issue = data.get("issue")
        if not issue:
            raise TicketNotFoundError(
                ticket_id=ticket_id,
                platform=self.name,
            )

        return self._map_to_generic(issue)

    def _map_to_generic(self, issue: dict) -> GenericTicket:
        """Map Linear API response to GenericTicket."""
        # Map state type to status
        state_type = issue.get("state", {}).get("type", "unstarted")
        status = self.STATE_TYPE_MAP.get(state_type, TicketStatus.UNKNOWN)

        # Get assignee name
        assignee = None
        if issue.get("assignee"):
            assignee = issue["assignee"].get("name") or issue["assignee"].get("email")

        # Extract labels
        labels = [l["name"] for l in issue.get("labels", {}).get("nodes", [])]

        return GenericTicket(
            id=issue["identifier"],
            platform=Platform.LINEAR,
            url=issue["url"],
            title=issue["title"],
            description=issue.get("description") or "",
            status=status,
            assignee=assignee,
            labels=labels,
            created_at=datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00")),
            platform_metadata={
                "team_key": issue.get("team", {}).get("key"),
                "team_name": issue.get("team", {}).get("name"),
                "priority": issue.get("priorityLabel"),
                "priority_value": issue.get("priority"),
                "state_name": issue.get("state", {}).get("name"),
                "parent_id": issue.get("parent", {}).get("identifier"),
            }
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Linear API access."""
        viewer_query = """
        query { viewer { id name email } }
        """
        try:
            data = self._execute_query(viewer_query, {})
            viewer = data.get("viewer", {})
            name = viewer.get("name") or viewer.get("email") or "Unknown"
            return True, f"Connected as {name}"
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
| API Key requests | 1,500/hour | Check response headers |
| Complexity limit | 10,000 points/request | Keep queries simple |

**Rate Limit Headers:**
```http
X-RateLimit-Requests-Limit: 1500
X-RateLimit-Requests-Remaining: 1487
X-RateLimit-Complexity-Limit: 10000
X-RateLimit-Complexity-Remaining: 9850
```

**Handling Strategy:**
1. Monitor `Remaining` headers
2. On 429 response, use `Retry-After` header
3. Implement exponential backoff

### 7.2 Identifier Ambiguity

Linear identifiers (`ENG-123`) look identical to Jira project keys.

**Resolution:**
```python
def detect_platform_for_id(identifier: str) -> Platform | None:
    """Attempt to detect platform for ambiguous identifier."""
    from specflow.config.manager import ConfigManager
    config = ConfigManager()
    config.load()

    default = config.get("DEFAULT_PLATFORM", "").upper()
    if default == "LINEAR":
        return Platform.LINEAR
    elif default == "JIRA":
        return Platform.JIRA

    # Could also try both APIs and see which succeeds
    return None  # Ambiguous - prompt user
```

### 7.3 Archived Issues

- Archived issues are still accessible via API
- Include `archivedAt` in metadata if present
- Consider warning user if issue is archived

### 7.4 Sub-Issues

- Sub-issues have a `parent` field
- Include parent identifier in metadata
- Consider fetching parent context if needed

### 7.5 Rich Description Content

- Linear descriptions use Markdown
- May contain images, code blocks, mentions
- Preserve as-is for spec generation

### 7.6 Team-Specific Workflows

- Each team can have custom workflow states
- Always use `state.type` for status mapping
- `state.name` is for display only

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
class TestLinearProvider:
    """Unit tests for LinearProvider."""

    def test_can_handle_linear_url(self):
        provider = LinearProvider()
        assert provider.can_handle("https://linear.app/myteam/issue/ENG-123")

    def test_can_handle_url_with_slug(self):
        provider = LinearProvider()
        assert provider.can_handle("https://linear.app/myteam/issue/ENG-123/implement-feature")

    def test_cannot_handle_jira_url(self):
        provider = LinearProvider()
        assert not provider.can_handle("https://company.atlassian.net/browse/PROJ-123")

    def test_parse_input_url(self):
        provider = LinearProvider()
        result = provider.parse_input("https://linear.app/team/issue/ENG-456")
        assert result == "ENG-456"

    @pytest.fixture
    def mock_issue_response(self):
        return {
            "issue": {
                "id": "uuid-123",
                "identifier": "ENG-42",
                "title": "Test Issue",
                "description": "Description here",
                "url": "https://linear.app/team/issue/ENG-42",
                "state": {"name": "In Progress", "type": "started"},
                "assignee": {"name": "Jane Dev", "email": "jane@co.com"},
                "labels": {"nodes": [{"name": "feature"}]},
                "createdAt": "2024-01-15T10:30:00.000Z",
                "updatedAt": "2024-01-16T14:00:00.000Z",
                "priority": 2,
                "priorityLabel": "High",
                "team": {"key": "ENG", "name": "Engineering"},
                "parent": None,
            }
        }

    def test_fetch_ticket_maps_correctly(self, mock_issue_response, mocker):
        provider = LinearProvider()
        mocker.patch.object(provider, "_execute_query", return_value=mock_issue_response)

        ticket = provider.fetch_ticket("ENG-42")

        assert ticket.id == "ENG-42"
        assert ticket.platform == Platform.LINEAR
        assert ticket.title == "Test Issue"
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.assignee == "Jane Dev"
        assert "feature" in ticket.labels
        assert ticket.platform_metadata["priority"] == "High"

    def test_status_mapping_backlog(self, mocker):
        provider = LinearProvider()
        response = {"issue": {"state": {"type": "backlog"}, ...}}
        mocker.patch.object(provider, "_execute_query", return_value=response)

        ticket = provider.fetch_ticket("ENG-1")
        assert ticket.status == TicketStatus.OPEN

    def test_status_mapping_completed(self, mocker):
        provider = LinearProvider()
        response = {"issue": {"state": {"type": "completed"}, ...}}
        mocker.patch.object(provider, "_execute_query", return_value=response)

        ticket = provider.fetch_ticket("ENG-1")
        assert ticket.status == TicketStatus.DONE
```

### 8.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("LINEAR_API_KEY"), reason="No Linear API key")
class TestLinearProviderIntegration:
    """Integration tests against real Linear API."""

    def test_connection_check(self):
        provider = LinearProvider()
        success, message = provider.check_connection()
        assert success
        assert "Connected as" in message

    def test_fetch_real_issue(self):
        # Requires a known issue ID in your Linear workspace
        provider = LinearProvider()
        ticket = provider.fetch_ticket("ENG-1")  # Adjust to real ID
        assert ticket.title
        assert ticket.platform == Platform.LINEAR
```

---

## Appendix A: GraphQL Schema Reference

### A.1 Issue Type Fields

```graphql
type Issue {
  id: ID!
  identifier: String!
  title: String!
  description: String
  url: String!
  state: WorkflowState!
  assignee: User
  labels: LabelConnection!
  createdAt: DateTime!
  updatedAt: DateTime!
  priority: Float!
  priorityLabel: String!
  team: Team!
  parent: Issue
  children: IssueConnection!
  archivedAt: DateTime
}
```

### A.2 WorkflowState Types

```graphql
enum WorkflowStateType {
  backlog
  unstarted
  started
  completed
  canceled
}
```

---

*End of Linear Integration Specification*

