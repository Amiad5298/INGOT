# Monday.com Integration Specification

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification details the implementation of the Monday.com provider for SPECFLOW's platform-agnostic issue tracker integration. Monday.com is a flexible work operating system (Work OS) used for project management, CRM, and various business workflows.

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
| Platform Name | Monday.com |
| API Type | GraphQL (API v2) |
| API Endpoint | `https://api.monday.com/v2` |
| Documentation | https://developer.monday.com/api-reference |
| Rate Limits | 10,000,000 complexity points/minute |

### 1.2 Key Concepts

| Monday.com Term | Generic Equivalent |
|-----------------|-------------------|
| Item | Ticket |
| Board | Project/Board |
| Group | Category/Section |
| Status Column | Status |
| People Column | Assignee |
| Tags Column | Labels |
| Workspace | Organization |

### 1.3 Data Model

Monday.com has a unique structure:
- **Workspaces** contain **Boards**
- **Boards** contain **Groups** and **Items**
- **Items** have **Columns** (custom fields)
- Column types include: Status, People, Text, Date, Tags, etc.

---

## 2. Authentication

### 2.1 Supported Methods

| Method | Use Case | Recommended |
|--------|----------|-------------|
| API Token (v2) | Individual users, CLI tools | ✅ Yes |
| OAuth 2.0 | Web applications | Not for CLI |

### 2.2 Obtaining API Token

1. Go to Monday.com → Profile Picture → Developers
2. Click "My Access Tokens" → "Show"
3. Copy the API token

### 2.3 Configuration

```bash
# ~/.specflow-config
MONDAY_API_TOKEN=eyJhbGciOiJIUzI1NiJ9.xxxxxxxxxxxx
MONDAY_DEFAULT_BOARD_ID=1234567890     # Optional: default board
```

### 2.4 Authentication Header

```http
Authorization: eyJhbGciOiJIUzI1NiJ9.xxxxxxxxxxxx
Content-Type: application/json
API-Version: 2024-01
```

---

## 3. API Endpoints

### 3.1 GraphQL Endpoint

All Monday.com API access is through a single GraphQL endpoint:

```
POST https://api.monday.com/v2
```

### 3.2 Fetch Item by ID

```graphql
query GetItem($id: ID!) {
  items(ids: [$id]) {
    id
    name
    created_at
    updated_at
    board {
      id
      name
    }
    group {
      id
      title
    }
    column_values {
      id
      title
      type
      text
      value
    }
    creator {
      id
      name
      email
    }
  }
}
```

### 3.3 Example API Call

```bash
curl -X POST https://api.monday.com/v2 \
  -H "Authorization: $MONDAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "API-Version: 2024-01" \
  -d '{
    "query": "query { items(ids: [1234567890]) { id name column_values { id title text } } }"
  }'
```

### 3.4 Example Response

```json
{
  "data": {
    "items": [{
      "id": "1234567890",
      "name": "Implement user authentication",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-18T14:20:00Z",
      "board": {
        "id": "9876543210",
        "name": "Engineering Tasks"
      },
      "group": {
        "id": "new_group",
        "title": "Sprint 5"
      },
      "column_values": [
        {
          "id": "status",
          "title": "Status",
          "type": "status",
          "text": "Working on it",
          "value": "{\"index\":1,\"label\":\"Working on it\"}"
        },
        {
          "id": "person",
          "title": "Assignee",
          "type": "people",
          "text": "Jane Developer",
          "value": "{\"personsAndTeams\":[{\"id\":12345,\"kind\":\"person\"}]}"
        },
        {
          "id": "tags",
          "title": "Tags",
          "type": "tag",
          "text": "backend, security",
          "value": "{\"tag_ids\":[111,222]}"
        }
      ],
      "creator": {
        "id": "67890",
        "name": "John Manager",
        "email": "john@company.com"
      }
    }]
  }
}
```

### 3.5 Connection Check Query

```graphql
query { me { id name email } }
```

---

## 4. Field Mapping

### 4.1 GenericTicket Mapping Table

| GenericTicket Field | Monday.com Field | Transform |
|---------------------|------------------|-----------|
| `id` | `id` | Direct (numeric string) |
| `platform` | - | `Platform.MONDAY` (constant) |
| `url` | Constructed | `https://{account}.monday.com/boards/{board_id}/pulses/{item_id}` |
| `title` | `name` | Direct |
| `description` | Text column or `name` | Find "Description" column |
| `status` | Status column | Map: see 4.2 |
| `assignee` | People column | Extract first person name |
| `labels` | Tags column | Parse tag names |
| `created_at` | `created_at` | Parse ISO 8601 |
| `updated_at` | `updated_at` | Parse ISO 8601 |
| `branch_summary` | Generated from `name` | Sanitize |
| `platform_metadata.board_id` | `board.id` | Direct |
| `platform_metadata.board_name` | `board.name` | Direct |
| `platform_metadata.group_title` | `group.title` | Direct |
| `platform_metadata.creator` | `creator.name` | Direct |

### 4.2 Status Mapping

Monday.com status columns have customizable labels. Common mappings:

| Monday.com Status Label | GenericTicket Status |
|------------------------|---------------------|
| `""` (blank) | `TicketStatus.OPEN` |
| `Working on it` | `TicketStatus.IN_PROGRESS` |
| `Stuck` | `TicketStatus.BLOCKED` |
| `Done` | `TicketStatus.DONE` |
| `Waiting for review` | `TicketStatus.REVIEW` |

**Dynamic Mapping Strategy:**
```python
STATUS_KEYWORDS = {
    TicketStatus.OPEN: ["", "not started", "new", "to do"],
    TicketStatus.IN_PROGRESS: ["working on it", "in progress", "active"],
    TicketStatus.REVIEW: ["review", "waiting for review", "pending"],
    TicketStatus.BLOCKED: ["stuck", "blocked", "on hold"],
    TicketStatus.DONE: ["done", "complete", "completed", "closed"],
}

def map_status(label: str) -> TicketStatus:
    label_lower = label.lower().strip()
    for status, keywords in STATUS_KEYWORDS.items():
        if label_lower in keywords:
            return status
    return TicketStatus.UNKNOWN
```

### 4.3 Column Value Parsing

Column values are JSON strings. Parse based on type:

```python
import json

def parse_column_value(column: dict) -> any:
    """Parse Monday.com column value."""
    col_type = column.get("type")
    value_str = column.get("value")
    text = column.get("text", "")

    if not value_str or value_str == "null":
        return text or None

    try:
        value = json.loads(value_str)
    except json.JSONDecodeError:
        return text

    if col_type == "status":
        return value.get("label", text)
    elif col_type == "people":
        persons = value.get("personsAndTeams", [])
        return [p["id"] for p in persons if p.get("kind") == "person"]
    elif col_type == "tag":
        return value.get("tag_ids", [])
    else:
        return text
```

---

## 5. URL Patterns

### 5.1 Supported URL Formats

| Pattern | Example | Regex |
|---------|---------|-------|
| Item URL | `https://mycompany.monday.com/boards/123/pulses/456` | `https?://([^.]+)\.monday\.com/boards/(\d+)/pulses/(\d+)` |
| Item URL (alt) | `https://mycompany.monday.com/boards/123/views/789/pulses/456` | Include view ID |
| ID Only | `456` (numeric) | `^\d+$` (requires board context) |

### 5.2 ID Normalization

Internal ticket ID format: `{board_id}:{item_id}`

Examples:
- `9876543210:1234567890`
- `123456:789012`

**Note:** Monday.com item IDs are globally unique, but we include board_id for context and URL construction.

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
    TicketNotFoundError,
    RateLimitError,
)

import requests
import json
import re
from datetime import datetime, timedelta

@ProviderRegistry.register
class MondayProvider(IssueTrackerProvider):
    """Monday.com item provider."""

    PLATFORM = Platform.MONDAY
    API_ENDPOINT = "https://api.monday.com/v2"

    ITEM_QUERY = """
    query GetItem($id: ID!) {
      items(ids: [$id]) {
        id
        name
        created_at
        updated_at
        board {
          id
          name
        }
        group {
          id
          title
        }
        column_values {
          id
          title
          type
          text
          value
        }
        creator {
          name
          email
        }
      }
    }
    """

    STATUS_KEYWORDS = {
        TicketStatus.OPEN: ["", "not started", "new", "to do"],
        TicketStatus.IN_PROGRESS: ["working on it", "in progress", "active"],
        TicketStatus.REVIEW: ["review", "waiting for review", "pending"],
        TicketStatus.BLOCKED: ["stuck", "blocked", "on hold"],
        TicketStatus.DONE: ["done", "complete", "completed", "closed"],
    }

    def __init__(self):
        self._token = None
        self._session = None
        self._account_slug = None

    @property
    def platform(self) -> Platform:
        return Platform.MONDAY

    @property
    def name(self) -> str:
        return "Monday.com"

    def _get_session(self) -> requests.Session:
        """Get configured requests session."""
        if self._session is None:
            from specflow.config.manager import ConfigManager
            config = ConfigManager()
            config.load()

            self._token = config.get("MONDAY_API_TOKEN", "")
            if not self._token:
                raise AuthenticationError("MONDAY_API_TOKEN not configured")

            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": self._token,
                "Content-Type": "application/json",
                "API-Version": "2024-01",
            })
        return self._session

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a Monday.com item reference."""
        patterns = [
            r"https?://[^.]+\.monday\.com/boards/\d+(/views/\d+)?/pulses/\d+",
        ]
        return any(re.match(p, input_str.strip()) for p in patterns)

    def parse_input(self, input_str: str) -> str:
        """Parse Monday.com item URL."""
        input_str = input_str.strip()

        # URL pattern
        match = re.match(
            r"https?://([^.]+)\.monday\.com/boards/(\d+)(?:/views/\d+)?/pulses/(\d+)",
            input_str
        )
        if match:
            self._account_slug = match.group(1)
            board_id, item_id = match.group(2), match.group(3)
            return f"{board_id}:{item_id}"

        raise ValueError(f"Invalid Monday.com item reference: {input_str}")

    def _execute_query(self, query: str, variables: dict) -> dict:
        """Execute GraphQL query."""
        session = self._get_session()

        response = session.post(
            self.API_ENDPOINT,
            json={"query": query, "variables": variables}
        )

        if response.status_code == 401:
            raise AuthenticationError("Monday.com authentication failed")
        elif response.status_code == 429:
            raise RateLimitError(60)

        response.raise_for_status()

        result = response.json()
        if "errors" in result:
            error_msg = result["errors"][0].get("message", "Unknown error")
            raise Exception(f"Monday.com API error: {error_msg}")

        return result.get("data", {})

    @cached_fetch(ttl=timedelta(hours=1))
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch item from Monday.com API."""
        # Parse ticket_id: "board_id:item_id"
        if ":" in ticket_id:
            board_id, item_id = ticket_id.split(":", 1)
        else:
            item_id = ticket_id
            board_id = None

        data = self._execute_query(self.ITEM_QUERY, {"id": item_id})

        items = data.get("items", [])
        if not items:
            raise TicketNotFoundError(f"Item not found: {ticket_id}")

        item = items[0]
        return self._map_to_generic(item)

    def _find_column(self, columns: list, col_type: str) -> dict | None:
        """Find column by type."""
        for col in columns:
            if col.get("type") == col_type:
                return col
        return None

    def _map_status(self, label: str) -> TicketStatus:
        """Map Monday.com status label to TicketStatus."""
        label_lower = label.lower().strip()
        for status, keywords in self.STATUS_KEYWORDS.items():
            if label_lower in keywords:
                return status
        return TicketStatus.UNKNOWN

    def _map_to_generic(self, item: dict) -> GenericTicket:
        """Map Monday.com API response to GenericTicket."""
        columns = item.get("column_values", [])
        board = item.get("board", {})

        # Find status column
        status_col = self._find_column(columns, "status")
        status_label = status_col.get("text", "") if status_col else ""
        status = self._map_status(status_label)

        # Find assignee (people column)
        people_col = self._find_column(columns, "people")
        assignee = people_col.get("text") if people_col else None

        # Find tags
        tags_col = self._find_column(columns, "tag")
        labels = []
        if tags_col and tags_col.get("text"):
            labels = [t.strip() for t in tags_col["text"].split(",")]

        # Find description (text column named "Description" or similar)
        description = ""
        for col in columns:
            if col.get("type") == "text" and "desc" in col.get("title", "").lower():
                description = col.get("text", "")
                break

        # Construct URL
        board_id = board.get("id", "")
        item_id = item["id"]
        url = f"https://monday.com/boards/{board_id}/pulses/{item_id}"
        if self._account_slug:
            url = f"https://{self._account_slug}.monday.com/boards/{board_id}/pulses/{item_id}"

        return GenericTicket(
            id=f"{board_id}:{item_id}",
            platform=Platform.MONDAY,
            url=url,
            title=item["name"],
            description=description,
            status=status,
            assignee=assignee,
            labels=labels,
            created_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
            platform_metadata={
                "board_id": board_id,
                "board_name": board.get("name"),
                "group_title": item.get("group", {}).get("title"),
                "creator": item.get("creator", {}).get("name"),
                "status_label": status_label,
            }
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Monday.com API access."""
        try:
            data = self._execute_query("query { me { id name email } }", {})
            me = data.get("me", {})
            name = me.get("name") or me.get("email") or "Unknown"
            return True, f"Connected as {name}"
        except AuthenticationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection failed: {e}"
```


---

## 7. Edge Cases & Limitations

### 7.1 Rate Limiting

Monday.com uses complexity-based rate limiting:

| Limit Type | Value |
|------------|-------|
| Complexity points | 10,000,000/minute |
| Query complexity | Varies by query |

**Complexity Calculation:**
- Base query: ~1-10 points
- Each field: ~1 point
- Nested objects: multiplied

**Handling Strategy:**
1. Keep queries minimal
2. Check `complexity` in response
3. On 429, wait and retry

### 7.2 No Standalone ID Pattern

Monday.com item IDs are numeric but not unique without board context:
- **Limitation:** Cannot detect platform from ID alone
- **Solution:** Require full URL or board context in config

### 7.3 Custom Column Types

Monday.com boards have custom columns. Handle gracefully:

```python
def _find_column_by_title(self, columns: list, title_pattern: str) -> dict | None:
    """Find column by title pattern (case-insensitive)."""
    pattern = title_pattern.lower()
    for col in columns:
        if pattern in col.get("title", "").lower():
            return col
    return None
```

### 7.4 Archived Items

- Archived items may not appear in default queries
- Use `state: all` parameter if needed
- Include archive status in metadata

### 7.5 Subitems

Monday.com supports subitems (nested items):
- Subitems have their own IDs
- Parent relationship via `parent_item` field
- Consider fetching parent context

### 7.6 Account Slug for URLs

The account slug (subdomain) is needed for proper URLs:
- Extract from input URL when available
- Store in instance for URL construction
- Fall back to generic `monday.com` domain

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
class TestMondayProvider:
    """Unit tests for MondayProvider."""

    def test_can_handle_monday_url(self):
        provider = MondayProvider()
        assert provider.can_handle(
            "https://mycompany.monday.com/boards/123/pulses/456"
        )

    def test_can_handle_url_with_view(self):
        provider = MondayProvider()
        assert provider.can_handle(
            "https://mycompany.monday.com/boards/123/views/789/pulses/456"
        )

    def test_cannot_handle_github(self):
        provider = MondayProvider()
        assert not provider.can_handle("https://github.com/owner/repo/issues/42")

    def test_parse_input_url(self):
        provider = MondayProvider()
        result = provider.parse_input(
            "https://acme.monday.com/boards/111/pulses/222"
        )
        assert result == "111:222"
        assert provider._account_slug == "acme"

    def test_map_status_working(self):
        provider = MondayProvider()
        assert provider._map_status("Working on it") == TicketStatus.IN_PROGRESS

    def test_map_status_done(self):
        provider = MondayProvider()
        assert provider._map_status("Done") == TicketStatus.DONE

    def test_map_status_unknown(self):
        provider = MondayProvider()
        assert provider._map_status("Custom Status") == TicketStatus.UNKNOWN

    @pytest.fixture
    def mock_item_response(self):
        return {
            "items": [{
                "id": "456",
                "name": "Test Item",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-16T14:00:00Z",
                "board": {"id": "123", "name": "Test Board"},
                "group": {"id": "grp1", "title": "Sprint 1"},
                "column_values": [
                    {"id": "status", "title": "Status", "type": "status", "text": "Working on it"},
                    {"id": "person", "title": "Assignee", "type": "people", "text": "Jane Dev"},
                    {"id": "tags", "title": "Tags", "type": "tag", "text": "backend, urgent"},
                ],
                "creator": {"name": "John Manager", "email": "john@co.com"}
            }]
        }

    def test_fetch_ticket_maps_correctly(self, mock_item_response, mocker):
        provider = MondayProvider()
        mocker.patch.object(provider, "_execute_query", return_value=mock_item_response)

        ticket = provider.fetch_ticket("123:456")

        assert ticket.id == "123:456"
        assert ticket.platform == Platform.MONDAY
        assert ticket.title == "Test Item"
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.assignee == "Jane Dev"
        assert "backend" in ticket.labels
```

### 8.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("MONDAY_API_TOKEN"),
    reason="No Monday.com API token"
)
class TestMondayProviderIntegration:
    """Integration tests against real Monday.com API."""

    def test_connection_check(self):
        provider = MondayProvider()
        success, message = provider.check_connection()
        assert success
        assert "Connected as" in message

    def test_fetch_real_item(self):
        # Requires a known item URL in your Monday.com account
        provider = MondayProvider()
        provider.parse_input("https://yourcompany.monday.com/boards/123/pulses/456")
        ticket = provider.fetch_ticket("123:456")
        assert ticket.title
        assert ticket.platform == Platform.MONDAY
```

---

## Appendix A: Column Types Reference

### A.1 Common Column Types

| Type | Description | Value Format |
|------|-------------|--------------|
| `status` | Status dropdown | `{"index": 1, "label": "Working on it"}` |
| `people` | Person assignment | `{"personsAndTeams": [{"id": 123, "kind": "person"}]}` |
| `tag` | Tags | `{"tag_ids": [1, 2, 3]}` |
| `text` | Plain text | `"Some text"` |
| `date` | Date picker | `{"date": "2024-01-15"}` |
| `timeline` | Date range | `{"from": "2024-01-01", "to": "2024-01-31"}` |
| `numbers` | Numeric | `"42"` |
| `link` | URL | `{"url": "https://...", "text": "Link"}` |

---

*End of Monday.com Integration Specification*

