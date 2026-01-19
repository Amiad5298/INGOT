# Azure DevOps Integration Specification

**Version:** 1.0
**Status:** Draft
**Author:** Architecture Team
**Date:** 2026-01-19

---

## Executive Summary

This specification details the implementation of the Azure DevOps provider for SPECFLOW's platform-agnostic issue tracker integration. Azure DevOps (formerly VSTS/TFS) is Microsoft's comprehensive DevOps platform with work item tracking, repos, pipelines, and more.

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
| Platform Name | Azure DevOps |
| API Type | REST |
| Base URL (Cloud) | `https://dev.azure.com/{organization}` |
| Base URL (Server) | `https://{server}/{collection}` |
| API Version | 7.1 (latest stable) |
| Documentation | https://learn.microsoft.com/en-us/rest/api/azure/devops |
| Rate Limits | Varies by service tier |

### 1.2 Key Concepts

| Azure DevOps Term | Generic Equivalent |
|-------------------|-------------------|
| Work Item | Ticket |
| Project | Project |
| State | Status |
| Assigned To | Assignee |
| Tags | Labels |
| Area Path | Category/Component |
| Iteration Path | Sprint |

### 1.3 Work Item Types

Azure DevOps supports multiple work item types:
- **Bug** - Defects
- **Task** - Work tasks
- **User Story** - Features (Agile)
- **Product Backlog Item** - Features (Scrum)
- **Feature** - Epics
- **Epic** - Initiatives

All are fetched via the same API endpoint.

---

## 2. Authentication

### 2.1 Supported Methods

| Method | Use Case | Recommended |
|--------|----------|-------------|
| Personal Access Token (PAT) | Individual users, CLI tools | ✅ Yes |
| OAuth 2.0 | Web applications | Not for CLI |
| Azure AD Token | Enterprise SSO | For enterprise |

### 2.2 Creating a PAT

1. Go to Azure DevOps → User Settings → Personal Access Tokens
2. Click "New Token"
3. Set scope: `Work Items (Read)` minimum
4. Copy the token

### 2.3 Configuration

```bash
# ~/.specflow-config
AZURE_DEVOPS_PAT=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AZURE_DEVOPS_ORG=myorganization          # Organization name
AZURE_DEVOPS_PROJECT=MyProject           # Optional: default project
AZURE_DEVOPS_SERVER_URL=                 # Optional: for on-prem (e.g., https://tfs.company.com/tfs)
```

### 2.4 Authentication Header

PAT uses Basic Auth with empty username:

```http
Authorization: Basic base64(":$PAT")
```

```python
import base64
auth_string = base64.b64encode(f":{pat}".encode()).decode()
headers = {"Authorization": f"Basic {auth_string}"}
```

---

## 3. API Endpoints

### 3.1 Get Work Item by ID

```http
GET https://dev.azure.com/{organization}/{project}/_apis/wit/workitems/{id}?api-version=7.1
```

**Example Request:**
```bash
curl -u ":$AZURE_DEVOPS_PAT" \
  "https://dev.azure.com/myorg/MyProject/_apis/wit/workitems/42?api-version=7.1"
```

### 3.2 Example Response

```json
{
  "id": 42,
  "rev": 5,
  "fields": {
    "System.Id": 42,
    "System.Title": "Implement user authentication",
    "System.Description": "<div>Add OAuth2 login flow...</div>",
    "System.State": "Active",
    "System.WorkItemType": "User Story",
    "System.AssignedTo": {
      "displayName": "Jane Developer",
      "uniqueName": "jane@company.com"
    },
    "System.Tags": "backend; security; priority-high",
    "System.CreatedDate": "2024-01-15T10:30:00Z",
    "System.ChangedDate": "2024-01-18T14:20:00Z",
    "System.AreaPath": "MyProject\\Backend",
    "System.IterationPath": "MyProject\\Sprint 5"
  },
  "url": "https://dev.azure.com/myorg/MyProject/_apis/wit/workitems/42",
  "_links": {
    "html": {
      "href": "https://dev.azure.com/myorg/MyProject/_workitems/edit/42"
    }
  }
}
```

### 3.3 Get Work Item Without Project

Work items can be fetched org-wide (without specifying project):

```http
GET https://dev.azure.com/{organization}/_apis/wit/workitems/{id}?api-version=7.1
```

### 3.4 Connection Check Endpoint

```http
GET https://dev.azure.com/{organization}/_apis/projects?api-version=7.1&$top=1
```

Returns list of projects. Success indicates valid authentication.

---

## 4. Field Mapping

### 4.1 GenericTicket Mapping Table

| GenericTicket Field | Azure DevOps Field | Transform |
|---------------------|-------------------|-----------|
| `id` | `id` | String conversion |
| `platform` | - | `Platform.AZURE_DEVOPS` (constant) |
| `url` | `_links.html.href` | Direct |
| `title` | `fields.System.Title` | Direct |
| `description` | `fields.System.Description` | Strip HTML |
| `status` | `fields.System.State` | Map: see 4.2 |
| `assignee` | `fields.System.AssignedTo.displayName` | Extract name |
| `labels` | `fields.System.Tags` | Split by `;` |
| `created_at` | `fields.System.CreatedDate` | Parse ISO 8601 |
| `updated_at` | `fields.System.ChangedDate` | Parse ISO 8601 |
| `branch_summary` | Generated from `title` | Sanitize |
| `platform_metadata.work_item_type` | `fields.System.WorkItemType` | Direct |
| `platform_metadata.area_path` | `fields.System.AreaPath` | Direct |
| `platform_metadata.iteration_path` | `fields.System.IterationPath` | Direct |
| `platform_metadata.organization` | From URL | Extracted |
| `platform_metadata.project` | From URL or field | Extracted |

### 4.2 Status Mapping

Azure DevOps states vary by process template (Agile, Scrum, CMMI):

| Azure DevOps State | GenericTicket Status |
|-------------------|---------------------|
| `New` | `TicketStatus.OPEN` |
| `Active` | `TicketStatus.IN_PROGRESS` |
| `Resolved` | `TicketStatus.REVIEW` |
| `Closed` | `TicketStatus.DONE` |
| `Removed` | `TicketStatus.CLOSED` |
| `To Do` (Scrum) | `TicketStatus.OPEN` |
| `In Progress` (Scrum) | `TicketStatus.IN_PROGRESS` |
| `Done` (Scrum) | `TicketStatus.DONE` |

**Fallback Strategy:**
```python
STATE_MAP = {
    "new": TicketStatus.OPEN,
    "to do": TicketStatus.OPEN,
    "active": TicketStatus.IN_PROGRESS,
    "in progress": TicketStatus.IN_PROGRESS,
    "resolved": TicketStatus.REVIEW,
    "closed": TicketStatus.DONE,
    "done": TicketStatus.DONE,
    "removed": TicketStatus.CLOSED,
}

def map_state(state: str) -> TicketStatus:
    return STATE_MAP.get(state.lower(), TicketStatus.UNKNOWN)
```

### 4.3 HTML Description Handling

Azure DevOps descriptions are HTML. Strip for plain text:

```python
import re
from html import unescape

def strip_html(html: str) -> str:
    """Convert HTML description to plain text."""
    if not html:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html)
    # Decode HTML entities
    text = unescape(text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

---

## 5. URL Patterns

### 5.1 Supported URL Formats

| Pattern | Example | Regex |
|---------|---------|-------|
| Cloud Work Item | `https://dev.azure.com/org/project/_workitems/edit/123` | `https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)` |
| Cloud Work Item (alt) | `https://org.visualstudio.com/project/_workitems/edit/123` | `https?://([^.]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)` |
| On-Prem TFS | `https://tfs.company.com/tfs/Collection/Project/_workitems/edit/123` | Custom pattern |
| ID Only | `123` (numeric) | `^\d+$` (requires context) |

### 5.2 ID Normalization

Internal ticket ID format: `{organization}/{project}#{id}`

Examples:
- `myorg/MyProject#42`
- `contoso/Backend#1234`

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
import base64
import re
from datetime import datetime, timedelta
from html import unescape

@ProviderRegistry.register
class AzureDevOpsProvider(IssueTrackerProvider):
    """Azure DevOps work item provider."""

    PLATFORM = Platform.AZURE_DEVOPS
    API_VERSION = "7.1"

    STATE_MAP = {
        "new": TicketStatus.OPEN,
        "to do": TicketStatus.OPEN,
        "active": TicketStatus.IN_PROGRESS,
        "in progress": TicketStatus.IN_PROGRESS,
        "resolved": TicketStatus.REVIEW,
        "closed": TicketStatus.DONE,
        "done": TicketStatus.DONE,
        "removed": TicketStatus.CLOSED,
    }

    def __init__(self):
        self._pat = None
        self._org = None
        self._session = None

    @property
    def platform(self) -> Platform:
        return Platform.AZURE_DEVOPS

    @property
    def name(self) -> str:
        return "Azure DevOps"

    def _get_session(self) -> requests.Session:
        """Get configured requests session."""
        if self._session is None:
            from specflow.config.manager import ConfigManager
            config = ConfigManager()
            config.load()

            self._pat = config.get("AZURE_DEVOPS_PAT", "")
            self._org = config.get("AZURE_DEVOPS_ORG", "")

            if not self._pat:
                raise AuthenticationError("AZURE_DEVOPS_PAT not configured")
            if not self._org:
                raise AuthenticationError("AZURE_DEVOPS_ORG not configured")

            # Basic auth with empty username
            auth_string = base64.b64encode(f":{self._pat}".encode()).decode()

            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Basic {auth_string}",
                "Content-Type": "application/json",
            })
        return self._session

    def _get_base_url(self) -> str:
        """Get API base URL."""
        from specflow.config.manager import ConfigManager
        config = ConfigManager()
        config.load()

        server_url = config.get("AZURE_DEVOPS_SERVER_URL", "")
        if server_url:
            return server_url.rstrip("/")
        return f"https://dev.azure.com/{self._org}"

    def can_handle(self, input_str: str) -> bool:
        """Check if input is an Azure DevOps work item reference."""
        patterns = [
            r"https?://dev\.azure\.com/[^/]+/[^/]+/_workitems/edit/\d+",
            r"https?://[^.]+\.visualstudio\.com/[^/]+/_workitems/edit/\d+",
        ]
        return any(re.match(p, input_str.strip()) for p in patterns)

    def parse_input(self, input_str: str) -> str:
        """Parse Azure DevOps work item URL."""
        input_str = input_str.strip()

        # dev.azure.com pattern
        match = re.match(
            r"https?://dev\.azure\.com/([^/]+)/([^/]+)/_workitems/edit/(\d+)",
            input_str
        )
        if match:
            org, project, work_item_id = match.groups()
            return f"{org}/{project}#{work_item_id}"

        # visualstudio.com pattern
        match = re.match(
            r"https?://([^.]+)\.visualstudio\.com/([^/]+)/_workitems/edit/(\d+)",
            input_str
        )
        if match:
            org, project, work_item_id = match.groups()
            return f"{org}/{project}#{work_item_id}"

        raise ValueError(f"Invalid Azure DevOps work item reference: {input_str}")

    @cached_fetch(ttl=timedelta(hours=1))
    def fetch_ticket(self, ticket_id: str) -> GenericTicket:
        """Fetch work item from Azure DevOps API."""
        # Parse ticket_id: "org/project#123"
        match = re.match(r"^([^/]+)/([^#]+)#(\d+)$", ticket_id)
        if not match:
            raise ValueError(f"Invalid ticket ID format: {ticket_id}")

        org, project, work_item_id = match.groups()

        session = self._get_session()
        url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{work_item_id}"
        response = session.get(url, params={"api-version": self.API_VERSION})

        if response.status_code == 404:
            raise TicketNotFoundError(f"Work item not found: {ticket_id}")
        elif response.status_code == 401:
            raise AuthenticationError("Azure DevOps authentication failed")
        elif response.status_code == 403:
            raise AuthenticationError("Access denied to work item")
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            raise RateLimitError(int(retry_after))

        response.raise_for_status()
        data = response.json()

        return self._map_to_generic(data, org, project)

    def _strip_html(self, html: str) -> str:
        """Convert HTML to plain text."""
        if not html:
            return ""
        text = re.sub(r'<[^>]+>', '', html)
        text = unescape(text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _map_to_generic(self, data: dict, org: str, project: str) -> GenericTicket:
        """Map Azure DevOps API response to GenericTicket."""
        fields = data.get("fields", {})

        # Map state
        state = fields.get("System.State", "")
        status = self.STATE_MAP.get(state.lower(), TicketStatus.UNKNOWN)

        # Get assignee
        assignee = None
        assigned_to = fields.get("System.AssignedTo")
        if assigned_to:
            assignee = assigned_to.get("displayName") or assigned_to.get("uniqueName")

        # Parse tags (semicolon-separated)
        tags_str = fields.get("System.Tags", "")
        labels = [t.strip() for t in tags_str.split(";") if t.strip()]

        # Get HTML link
        html_url = data.get("_links", {}).get("html", {}).get("href", "")

        return GenericTicket(
            id=f"{org}/{project}#{data['id']}",
            platform=Platform.AZURE_DEVOPS,
            url=html_url,
            title=fields.get("System.Title", ""),
            description=self._strip_html(fields.get("System.Description", "")),
            status=status,
            assignee=assignee,
            labels=labels,
            created_at=datetime.fromisoformat(
                fields.get("System.CreatedDate", "").replace("Z", "+00:00")
            ),
            updated_at=datetime.fromisoformat(
                fields.get("System.ChangedDate", "").replace("Z", "+00:00")
            ),
            platform_metadata={
                "organization": org,
                "project": project,
                "work_item_type": fields.get("System.WorkItemType"),
                "area_path": fields.get("System.AreaPath"),
                "iteration_path": fields.get("System.IterationPath"),
                "state_name": state,
            }
        )

    def check_connection(self) -> tuple[bool, str]:
        """Verify Azure DevOps API access."""
        try:
            session = self._get_session()
            url = f"{self._get_base_url()}/_apis/projects"
            response = session.get(url, params={"api-version": self.API_VERSION, "$top": 1})

            if response.status_code == 200:
                projects = response.json().get("value", [])
                if projects:
                    return True, f"Connected to {self._org} (found {projects[0]['name']})"
                return True, f"Connected to {self._org}"
            return False, f"API error: {response.status_code}"
        except AuthenticationError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Connection failed: {e}"
```


---

## 7. Edge Cases & Limitations

### 7.1 Rate Limiting

Azure DevOps uses a "Resource Unit" (RU) based rate limiting:

| Tier | Limit |
|------|-------|
| Basic | 200 RUs per 5 minutes |
| Stakeholder | 100 RUs per 5 minutes |

**Rate Limit Headers:**
```http
X-RateLimit-Resource: core
X-RateLimit-Delay: 0.5
Retry-After: 30
```

**Handling Strategy:**
1. Check for 429 status code
2. Use `Retry-After` header for delay
3. Implement exponential backoff

### 7.2 On-Premises TFS/Azure DevOps Server

```python
def _get_base_url(self) -> str:
    """Support on-prem installations."""
    server_url = config.get("AZURE_DEVOPS_SERVER_URL", "")
    if server_url:
        # On-prem: https://tfs.company.com/tfs/DefaultCollection
        return server_url.rstrip("/")
    # Cloud
    return f"https://dev.azure.com/{self._org}"
```

### 7.3 Work Item ID Ambiguity

Work item IDs are numeric and org-scoped. Without URL context:
- Require `AZURE_DEVOPS_ORG` and `AZURE_DEVOPS_PROJECT` config
- Or require full URL input

### 7.4 HTML Descriptions

- Descriptions are stored as HTML
- May contain rich formatting, images, tables
- Strip HTML for plain text, preserve for full context

### 7.5 Custom Fields

Organizations may have custom fields. Access via:
```python
custom_value = fields.get("Custom.MyField")
```

Store unknown fields in `platform_metadata.custom_fields`.

### 7.6 Deleted Work Items

- Deleted items return 404
- Recycle bin items may be accessible with special permissions
- Handle 404 as "not found"

---

## 8. Testing Strategy

### 8.1 Unit Tests

```python
class TestAzureDevOpsProvider:
    """Unit tests for AzureDevOpsProvider."""

    def test_can_handle_dev_azure_url(self):
        provider = AzureDevOpsProvider()
        assert provider.can_handle(
            "https://dev.azure.com/myorg/MyProject/_workitems/edit/42"
        )

    def test_can_handle_visualstudio_url(self):
        provider = AzureDevOpsProvider()
        assert provider.can_handle(
            "https://myorg.visualstudio.com/MyProject/_workitems/edit/42"
        )

    def test_cannot_handle_github(self):
        provider = AzureDevOpsProvider()
        assert not provider.can_handle("https://github.com/owner/repo/issues/42")

    def test_parse_input_dev_azure(self):
        provider = AzureDevOpsProvider()
        result = provider.parse_input(
            "https://dev.azure.com/contoso/Backend/_workitems/edit/123"
        )
        assert result == "contoso/Backend#123"

    def test_strip_html(self):
        provider = AzureDevOpsProvider()
        html = "<div><p>Hello <strong>World</strong></p></div>"
        assert provider._strip_html(html) == "Hello World"

    @pytest.fixture
    def mock_work_item_response(self):
        return {
            "id": 42,
            "fields": {
                "System.Title": "Test Work Item",
                "System.Description": "<div>Description here</div>",
                "System.State": "Active",
                "System.WorkItemType": "User Story",
                "System.AssignedTo": {"displayName": "Jane Dev"},
                "System.Tags": "backend; priority-high",
                "System.CreatedDate": "2024-01-15T10:30:00Z",
                "System.ChangedDate": "2024-01-16T14:00:00Z",
            },
            "_links": {
                "html": {"href": "https://dev.azure.com/org/proj/_workitems/edit/42"}
            }
        }

    def test_fetch_ticket_maps_correctly(self, mock_work_item_response, mocker):
        provider = AzureDevOpsProvider()
        mocker.patch.object(provider, "_get_session")
        provider._get_session().get.return_value.status_code = 200
        provider._get_session().get.return_value.json.return_value = mock_work_item_response

        ticket = provider.fetch_ticket("myorg/MyProject#42")

        assert ticket.id == "myorg/MyProject#42"
        assert ticket.platform == Platform.AZURE_DEVOPS
        assert ticket.title == "Test Work Item"
        assert ticket.status == TicketStatus.IN_PROGRESS
        assert "backend" in ticket.labels
        assert "priority-high" in ticket.labels
```

### 8.2 Integration Tests

```python
@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AZURE_DEVOPS_PAT"),
    reason="No Azure DevOps PAT"
)
class TestAzureDevOpsProviderIntegration:
    """Integration tests against real Azure DevOps API."""

    def test_connection_check(self):
        provider = AzureDevOpsProvider()
        success, message = provider.check_connection()
        assert success
        assert "Connected" in message

    def test_fetch_real_work_item(self):
        # Requires a known work item ID in your org
        provider = AzureDevOpsProvider()
        ticket = provider.fetch_ticket("myorg/MyProject#1")
        assert ticket.title
        assert ticket.platform == Platform.AZURE_DEVOPS
```

---

## Appendix A: API Field Reference

### A.1 Common System Fields

| Field | Description |
|-------|-------------|
| `System.Id` | Work item ID |
| `System.Title` | Title |
| `System.Description` | HTML description |
| `System.State` | Current state |
| `System.WorkItemType` | Type (Bug, Task, etc.) |
| `System.AssignedTo` | Assigned user object |
| `System.Tags` | Semicolon-separated tags |
| `System.CreatedDate` | Creation timestamp |
| `System.ChangedDate` | Last modified timestamp |
| `System.AreaPath` | Area path |
| `System.IterationPath` | Iteration/sprint path |
| `System.Reason` | State change reason |

---

*End of Azure DevOps Integration Specification*

