# Trello Integration Specification

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification details the implementation of the Trello provider for SPECFLOW's platform-agnostic issue tracker integration. Trello is a visual collaboration tool using boards, lists, and cards for project management.

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
| Platform Name | Trello |
| API Type | REST |
| Base URL | `https://api.trello.com/1` |
| Documentation | https://developer.atlassian.com/cloud/trello/rest |
| Rate Limits | 100 requests/10 seconds per token, 300/10s per key |

### 1.2 Key Concepts

| Trello Term | Generic Equivalent |
|-------------|-------------------|
| Card | Ticket |
| Board | Project/Board |
| List | Status/Column |
| Label | Label/Tag |
| Member | Assignee |
| Checklist | Subtasks |

### 1.3 Data Model

Trello's hierarchy:
- **Workspaces** (formerly Organizations) contain **Boards**
- **Boards** contain **Lists** and **Cards**
- **Cards** have **Labels**, **Members**, **Checklists**, **Attachments**
- **Lists** represent workflow stages (e.g., "To Do", "In Progress", "Done")

---

## 2. Authentication

### 2.1 Supported Methods

| Method | Use Case | Recommended |
|--------|----------|-------------|
| API Key + Token | CLI tools, scripts | ✅ Yes |
| OAuth 1.0a | Web applications | Not for CLI |

### 2.2 Obtaining Credentials

1. **API Key:** Go to https://trello.com/power-ups/admin → Create Power-Up → Get API Key
2. **Token:** Visit `https://trello.com/1/authorize?expiration=never&scope=read&response_type=token&key={YOUR_API_KEY}`
3. Authorize and copy the token

### 2.3 Configuration

```bash
# ~/.specflow-config
TRELLO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TRELLO_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TRELLO_DEFAULT_BOARD_ID=                # Optional: default board
```

### 2.4 Authentication Parameters

Trello uses query parameters for auth:

```http
GET https://api.trello.com/1/cards/{id}?key={API_KEY}&token={TOKEN}
```

---

## 3. API Endpoints

### 3.1 Get Card by ID

```http
GET https://api.trello.com/1/cards/{id}
```

**Query Parameters:**
- `key` (required): API key
- `token` (required): User token
- `fields`: Comma-separated list of fields (default: all)
- `members`: Include member objects (true/false)
- `member_fields`: Fields to include for members
- `labels`: Include label objects (true/false)
- `list`: Include list object (true/false)
- `board`: Include board object (true/false)

### 3.2 Example Request

```bash
curl "https://api.trello.com/1/cards/abc123def456?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN&members=true&list=true&board=true"
```

### 3.3 Example Response

```json
{
  "id": "abc123def456789",
  "name": "Implement user authentication",
  "desc": "Add OAuth2 login flow with Google and GitHub providers.",
  "closed": false,
  "idBoard": "board123",
  "idList": "list456",
  "url": "https://trello.com/c/abc123/42-implement-user-authentication",
  "shortUrl": "https://trello.com/c/abc123",
  "dateLastActivity": "2024-01-18T14:20:00.000Z",
  "labels": [
    {"id": "label1", "name": "Feature", "color": "green"},
    {"id": "label2", "name": "Backend", "color": "blue"}
  ],
  "members": [
    {"id": "member1", "fullName": "Jane Developer", "username": "janedev"}
  ],
  "list": {
    "id": "list456",
    "name": "In Progress"
  },
  "board": {
    "id": "board123",
    "name": "Engineering Tasks"
  },
  "due": "2024-01-25T17:00:00.000Z",
  "dueComplete": false,
  "idMembers": ["member1"],
  "idLabels": ["label1", "label2"]
}
```

### 3.4 Get Card by Short Link

Cards can be fetched by their short link ID (from URL):

```http
GET https://api.trello.com/1/cards/{shortLink}
```

Example: For URL `https://trello.com/c/abc123/42-card-name`, use `abc123`.

### 3.5 Connection Check Endpoint

```http
GET https://api.trello.com/1/members/me?key={key}&token={token}
```

Returns authenticated user info.

---

## 4. Field Mapping

### 4.1 GenericTicket Mapping Table

| GenericTicket Field | Trello API Field | Transform |
|---------------------|------------------|-----------|
| `id` | `shortLink` or `id` | Prefer shortLink |
| `platform` | - | `Platform.TRELLO` (constant) |
| `url` | `url` or `shortUrl` | Direct |
| `title` | `name` | Direct |
| `description` | `desc` | Direct (markdown) |
| `status` | `list.name` | Map: see 4.2 |
| `type` | `labels[*].name` | Map: see 4.4 |
| `assignee` | `members[0].fullName` | First member |
| `labels` | `labels[*].name` | Extract names |
| `created_at` | Derived from `id` | ObjectId timestamp |
| `updated_at` | `dateLastActivity` | Parse ISO 8601 |
| `branch_summary` | Generated from `name` | Sanitize |
| `platform_metadata.board_id` | `idBoard` | Direct |
| `platform_metadata.board_name` | `board.name` | If included |
| `platform_metadata.list_id` | `idList` | Direct |
| `platform_metadata.list_name` | `list.name` | If included |
| `platform_metadata.due_date` | `due` | If set |
| `platform_metadata.is_closed` | `closed` | Boolean |

### 4.2 Status Mapping

Trello uses list names as status. Common mappings:

| Trello List Name | GenericTicket Status |
|-----------------|---------------------|
| `To Do` | `TicketStatus.OPEN` |
| `Backlog` | `TicketStatus.OPEN` |
| `In Progress` | `TicketStatus.IN_PROGRESS` |
| `Doing` | `TicketStatus.IN_PROGRESS` |
| `Review` | `TicketStatus.REVIEW` |
| `In Review` | `TicketStatus.REVIEW` |
| `Done` | `TicketStatus.DONE` |
| `Complete` | `TicketStatus.DONE` |
| `Blocked` | `TicketStatus.BLOCKED` |

**Dynamic Mapping:**
```python
LIST_STATUS_MAP = {
    TicketStatus.OPEN: ["to do", "backlog", "todo", "new", "inbox"],
    TicketStatus.IN_PROGRESS: ["in progress", "doing", "active", "working"],
    TicketStatus.REVIEW: ["review", "in review", "testing", "qa"],
    TicketStatus.BLOCKED: ["blocked", "on hold", "waiting"],
    TicketStatus.DONE: ["done", "complete", "completed", "closed", "archived"],
}

def map_list_to_status(list_name: str) -> TicketStatus:
    name_lower = list_name.lower().strip()
    for status, keywords in LIST_STATUS_MAP.items():
        if name_lower in keywords:
            return status
    return TicketStatus.UNKNOWN
```

### 4.3 Created Date from ObjectId

Trello card IDs are MongoDB ObjectIds. Extract creation timestamp:

```python
from datetime import datetime

def get_created_at_from_id(card_id: str) -> datetime:
    """Extract creation timestamp from Trello card ID (ObjectId)."""
    # First 8 characters are hex timestamp
    timestamp_hex = card_id[:8]
    timestamp = int(timestamp_hex, 16)
    return datetime.utcfromtimestamp(timestamp)
```

### 4.4 Type Mapping

Trello uses labels for categorization. Type is inferred from label names:

**Type Mapping Strategy:**

```python
TYPE_KEYWORDS = {
    TicketType.BUG: ["bug", "defect", "fix", "error", "issue"],
    TicketType.FEATURE: ["feature", "enhancement", "story", "new"],
    TicketType.TASK: ["task", "chore", "todo", "action"],
    TicketType.MAINTENANCE: ["maintenance", "tech debt", "refactor", "cleanup", "infra"],
}

def map_type(labels: list[str]) -> TicketType:
    """Map Trello labels to TicketType.

    Args:
        labels: List of label names from the card

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

**Common Trello Label Mappings:**

| Trello Label | TicketType |
|--------------|------------|
| `Bug` | `TicketType.BUG` |
| `bug` | `TicketType.BUG` |
| `Feature` | `TicketType.FEATURE` |
| `Enhancement` | `TicketType.FEATURE` |
| `Task` | `TicketType.TASK` |
| `Chore` | `TicketType.TASK` |
| `Tech Debt` | `TicketType.MAINTENANCE` |
| `Maintenance` | `TicketType.MAINTENANCE` |

**Note:** Trello labels can also have colors without names. Named labels are preferred for type inference.

---

## 5. URL Patterns

### 5.1 Supported URL Formats

| Pattern | Example | Regex |
|---------|---------|-------|
| Card URL | `https://trello.com/c/abc123/42-card-name` | `https?://trello\.com/c/([a-zA-Z0-9]+)` |
| Card URL (short) | `https://trello.com/c/abc123` | Same regex |
| Short Link only | `abc123` | `^[a-zA-Z0-9]{8}$` (8 chars) |

### 5.2 ID Normalization

Internal ticket ID format: `{shortLink}`

Examples:
- `abc123de`
- `XyZ789Ab`

**Note:** Trello short links are globally unique, so no board context needed.

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
import re
from datetime import datetime, timedelta, timezone

@ProviderRegistry.register
class TrelloProvider(IssueTrackerProvider):
    """Trello card provider."""

    PLATFORM = Platform.TRELLO
    API_BASE = "https://api.trello.com/1"

    LIST_STATUS_MAP = {
        TicketStatus.OPEN: ["to do", "backlog", "todo", "new", "inbox"],
        TicketStatus.IN_PROGRESS: ["in progress", "doing", "active", "working"],
        TicketStatus.REVIEW: ["review", "in review", "testing", "qa"],
        TicketStatus.BLOCKED: ["blocked", "on hold", "waiting"],
        TicketStatus.DONE: ["done", "complete", "completed", "closed", "archived"],
    }

    def __init__(self):
        self._api_key = None
        self._token = None
        self._session = None

    @property
    def platform(self) -> Platform:
        return Platform.TRELLO

    @property
    def name(self) -> str:
        return "Trello"

    def _get_session(self) -> requests.Session:
        """Get configured requests session."""
        if self._session is None:
            from specflow.config.manager import ConfigManager
            config = ConfigManager()
            config.load()

            self._api_key = config.get("TRELLO_API_KEY", "")
            self._token = config.get("TRELLO_TOKEN", "")

            if not self._api_key:
                raise AuthenticationError("TRELLO_API_KEY not configured")
            if not self._token:
                raise AuthenticationError("TRELLO_TOKEN not configured")

            self._session = requests.Session()
        return self._session

    def _get_auth_params(self) -> dict:
        """Get authentication query parameters."""
        return {"key": self._api_key, "token": self._token}

    def can_handle(self, input_str: str) -> bool:
        """Check if input is a Trello card reference."""
        patterns = [
            r"https?://trello\.com/c/[a-zA-Z0-9]+",
        ]
        return any(re.match(p, input_str.strip()) for p in patterns)

    def parse_input(self, input_str: str) -> str:
        """Parse Trello card URL or short link."""
        input_str = input_str.strip()

        # URL pattern
        match = re.match(r"https?://trello\.com/c/([a-zA-Z0-9]+)", input_str)
        if match:
            return match.group(1)

        # Short link pattern (8 alphanumeric chars)
        if re.match(r"^[a-zA-Z0-9]{8}$", input_str):
            return input_str

        raise ValueError(f"Invalid Trello card reference: {input_str}")

    def _get_created_at(self, card_id: str) -> datetime:
        """Extract creation timestamp from card ID (ObjectId)."""
        try:
            timestamp_hex = card_id[:8]
            timestamp = int(timestamp_hex, 16)
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (ValueError, IndexError):
            return datetime.now(tz=timezone.utc)

    def _map_list_to_status(self, list_name: str) -> TicketStatus:
        """Map Trello list name to TicketStatus."""
        name_lower = list_name.lower().strip()
        for status, keywords in self.LIST_STATUS_MAP.items():
            if name_lower in keywords:
                return status
        return TicketStatus.UNKNOWN

    @cached_fetch(ttl=timedelta(hours=1))
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch card from Trello API."""
        session = self._get_session()

        params = {
            **self._get_auth_params(),
            "members": "true",
            "member_fields": "fullName,username",
            "list": "true",
            "board": "true",
            "board_fields": "name",
        }

        response = session.get(
            f"{self.API_BASE}/cards/{ticket_id}",
            params=params
        )

        if response.status_code == 404:
            raise TicketNotFoundError(
                ticket_id=ticket_id,
                platform=self.name,
            )
        elif response.status_code == 401:
            raise AuthenticationError("Trello authentication failed")
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "10")
            raise RateLimitError(int(retry_after))

        response.raise_for_status()
        data = response.json()

        return self._map_to_generic(data)

    def _map_to_generic(self, data: dict) -> GenericTicket:
        """Map Trello API response to GenericTicket."""
        # Get list name for status
        list_info = data.get("list", {})
        list_name = list_info.get("name", "")
        status = self._map_list_to_status(list_name)

        # Handle closed cards
        if data.get("closed"):
            status = TicketStatus.CLOSED

        # Get first assignee
        members = data.get("members", [])
        assignee = members[0].get("fullName") if members else None

        # Get labels
        labels = [l.get("name") for l in data.get("labels", []) if l.get("name")]

        # Get board info
        board = data.get("board", {})

        # Parse dates
        updated_at = datetime.fromisoformat(
            data["dateLastActivity"].replace("Z", "+00:00")
        ) if data.get("dateLastActivity") else datetime.now(tz=timezone.utc)

        created_at = self._get_created_at(data["id"])

        return GenericTicket(
            id=data.get("shortLink", data["id"]),
            platform=Platform.TRELLO,
            url=data.get("url") or data.get("shortUrl", ""),
            title=data["name"],
            description=data.get("desc", ""),
            status=status,
            assignee=assignee,
            labels=labels,
            created_at=created_at,
            updated_at=updated_at,
            platform_metadata={
                "board_id": data.get("idBoard"),
                "board_name": board.get("name"),
                "list_id": data.get("idList"),
                "list_name": list_name,
                "due_date": data.get("due"),
                "due_complete": data.get("dueComplete"),
                "is_closed": data.get("closed", False),
                "short_link": data.get("shortLink"),
            }
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Trello API access."""
        try:
            session = self._get_session()
            response = session.get(
                f"{self.API_BASE}/members/me",
                params=self._get_auth_params()
            )

            if response.status_code == 200:
                user = response.json()
                name = user.get("fullName") or user.get("username") or "Unknown"
                return True, f"Connected as {name}"
            return False, f"API error: {response.status_code}"
        except AuthenticationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection failed: {e}"
```


---

## 7. Edge Cases & Limitations

### 7.1 Rate Limiting

| Limit Type | Value |
|------------|-------|
| Per token | 100 requests/10 seconds |
| Per API key | 300 requests/10 seconds |

**Rate Limit Headers:**
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
Retry-After: 10
```

**Handling Strategy:**
1. Check `X-RateLimit-Remaining` header
2. On 429, use `Retry-After` header
3. Implement token bucket or sliding window

### 7.2 Archived Cards

- Archived cards have `closed: true`
- Still accessible via API
- Map to `TicketStatus.CLOSED`

### 7.3 Private Boards

- Requires token with access to the board
- Returns 401 if no access
- Handle as "not found or no access"

### 7.4 Card ID vs Short Link

- Full ID: 24-character hex string (MongoDB ObjectId)
- Short Link: 8-character alphanumeric
- Both work for API calls
- Prefer short link for readability

### 7.5 No Created Date Field

Trello doesn't expose `createdAt` directly:
- Extract from card ID (ObjectId timestamp)
- First 8 hex chars = Unix timestamp

### 7.6 Checklists and Attachments

- Cards may have checklists (subtasks)
- Cards may have attachments
- Consider including in metadata for context

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
class TestTrelloProvider:
    """Unit tests for TrelloProvider."""

    def test_can_handle_trello_url(self):
        provider = TrelloProvider()
        assert provider.can_handle("https://trello.com/c/abc123de/42-card-name")

    def test_can_handle_short_url(self):
        provider = TrelloProvider()
        assert provider.can_handle("https://trello.com/c/abc123de")

    def test_cannot_handle_github(self):
        provider = TrelloProvider()
        assert not provider.can_handle("https://github.com/owner/repo/issues/42")

    def test_parse_input_url(self):
        provider = TrelloProvider()
        result = provider.parse_input("https://trello.com/c/XyZ789Ab/99-my-card")
        assert result == "XyZ789Ab"

    def test_parse_input_short_link(self):
        provider = TrelloProvider()
        result = provider.parse_input("XyZ789Ab")
        assert result == "XyZ789Ab"

    def test_map_list_to_status_todo(self):
        provider = TrelloProvider()
        assert provider._map_list_to_status("To Do") == TicketStatus.OPEN

    def test_map_list_to_status_in_progress(self):
        provider = TrelloProvider()
        assert provider._map_list_to_status("In Progress") == TicketStatus.IN_PROGRESS

    def test_map_list_to_status_done(self):
        provider = TrelloProvider()
        assert provider._map_list_to_status("Done") == TicketStatus.DONE

    def test_get_created_at_from_id(self):
        provider = TrelloProvider()
        # Known ObjectId: 507f1f77bcf86cd799439011
        # Timestamp: 1350844279 = 2012-10-21T21:11:19Z
        created = provider._get_created_at("507f1f77bcf86cd799439011")
        assert created.year == 2012
        assert created.month == 10

    @pytest.fixture
    def mock_card_response(self):
        return {
            "id": "507f1f77bcf86cd799439011",
            "shortLink": "abc123de",
            "name": "Test Card",
            "desc": "Description here",
            "closed": False,
            "url": "https://trello.com/c/abc123de/42-test-card",
            "dateLastActivity": "2024-01-16T14:00:00.000Z",
            "list": {"id": "list1", "name": "In Progress"},
            "board": {"id": "board1", "name": "Test Board"},
            "members": [{"fullName": "Jane Dev", "username": "janedev"}],
            "labels": [{"name": "Feature", "color": "green"}],
            "due": None,
            "dueComplete": False,
        }

    def test_fetch_ticket_maps_correctly(self, mock_card_response, mocker):
        provider = TrelloProvider()
        mocker.patch.object(provider, "_get_session")
        provider._get_session().get.return_value.status_code = 200
        provider._get_session().get.return_value.json.return_value = mock_card_response

        ticket = provider.fetch_ticket("abc123de")

        assert ticket.id == "abc123de"
        assert ticket.platform == Platform.TRELLO
        assert ticket.title == "Test Card"
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert ticket.assignee == "Jane Dev"
        assert "Feature" in ticket.labels
```

### 8.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("TRELLO_API_KEY") or not os.environ.get("TRELLO_TOKEN"),
    reason="No Trello credentials"
)
class TestTrelloProviderIntegration:
    """Integration tests against real Trello API."""

    def test_connection_check(self):
        provider = TrelloProvider()
        success, message = provider.check_connection()
        assert success
        assert "Connected as" in message

    def test_fetch_real_card(self):
        # Requires a known card URL in your Trello account
        provider = TrelloProvider()
        short_link = provider.parse_input("https://trello.com/c/yourcard")
        ticket = provider.fetch_ticket(short_link)
        assert ticket.title
        assert ticket.platform == Platform.TRELLO
```

---

## Appendix A: API Response Fields

### A.1 Card Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Full card ID (ObjectId) |
| `shortLink` | string | 8-char short link |
| `name` | string | Card title |
| `desc` | string | Description (markdown) |
| `closed` | boolean | Is archived |
| `url` | string | Full URL |
| `shortUrl` | string | Short URL |
| `idBoard` | string | Board ID |
| `idList` | string | List ID |
| `idMembers` | array | Member IDs |
| `idLabels` | array | Label IDs |
| `due` | string | Due date (ISO 8601) |
| `dueComplete` | boolean | Due date completed |
| `dateLastActivity` | string | Last activity (ISO 8601) |

### A.2 Label Colors

Trello labels have predefined colors:
`green`, `yellow`, `orange`, `red`, `purple`, `blue`, `sky`, `lime`, `pink`, `black`

---

*End of Trello Integration Specification*

