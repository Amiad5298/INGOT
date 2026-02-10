"""Base classes for platform-agnostic issue tracker integration.

This module defines:
- Platform enum for supported issue tracking platforms
- TicketStatus and TicketType enums for normalized ticket states
- GenericTicket dataclass for platform-agnostic ticket representation
- IssueTrackerProvider abstract base class that all providers must implement

All platform-specific providers must implement the IssueTrackerProvider
interface, ensuring consistent behavior and enabling the Open/Closed principle.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, ClassVar, TypedDict

if TYPE_CHECKING:
    from ingot.integrations.jira import JiraTicket

# Pre-compiled regex patterns for performance optimization
# These are compiled once at module load time instead of on each function call
_PATTERN_NON_ALPHANUMERIC_HYPHEN = re.compile(r"[^a-z0-9-]")
_PATTERN_MULTIPLE_HYPHENS = re.compile(r"-+")
_PATTERN_MULTIPLE_UNDERSCORES = re.compile(r"_+")


def sanitize_for_branch_component(value: str) -> str:
    """Sanitize a string component for use in git branch names.

    This is the core sanitizer that ensures output contains only git-safe
    characters: lowercase letters, digits, and hyphens.

    Steps:
    1. Lowercase the input
    2. Replace any character not in [a-z0-9-] with hyphen
    3. Collapse multiple consecutive hyphens
    4. Strip leading/trailing hyphens
    5. Handle empty result gracefully

    Args:
        value: The string to sanitize

    Returns:
        A git-safe string containing only [a-z0-9-]
    """
    if not value:
        return ""
    # Lowercase first
    result = value.lower()
    # Replace any non-[a-z0-9-] with hyphens (using pre-compiled pattern)
    result = _PATTERN_NON_ALPHANUMERIC_HYPHEN.sub("-", result)
    # Collapse multiple hyphens (using pre-compiled pattern)
    result = _PATTERN_MULTIPLE_HYPHENS.sub("-", result)
    # Strip leading/trailing hyphens
    result = result.strip("-")
    return result


def sanitize_title_for_branch(title: str, max_length: int = 50) -> str:
    """Sanitize a title string for use in git branch names.

    Converts title to lowercase, replaces non-alphanumeric characters
    with hyphens, collapses consecutive hyphens, and strips leading/trailing
    hyphens. Ensures output does not end with a hyphen after truncation.

    Args:
        title: The title to sanitize
        max_length: Maximum length of the output (default: 50)

    Returns:
        A git-friendly branch summary string (max `max_length` chars,
        no trailing hyphens)
    """
    # Truncate first, then sanitize to get consistent behavior
    truncated = title[:max_length]
    result = sanitize_for_branch_component(truncated)
    # Ensure truncation didn't leave trailing hyphens
    return result.rstrip("-")


def _normalize_for_json(obj: Any) -> Any:
    """Recursively normalize an object for JSON serialization.

    Handles datetime, set/frozenset, Enum, and arbitrary objects so that
    platform_metadata can always be serialized without raising TypeError.
    """
    # Primitives that are already JSON-safe
    if obj is None or isinstance(obj, bool | int | float | str):
        return obj

    # datetime → ISO format string
    if isinstance(obj, datetime):
        return obj.isoformat()

    # set/frozenset → sorted list for deterministic output
    if isinstance(obj, set | frozenset):
        try:
            return sorted(_normalize_for_json(item) for item in obj)
        except TypeError:
            # Elements not comparable, just convert without sorting
            return [_normalize_for_json(item) for item in obj]

    # Enum → value or name
    if isinstance(obj, Enum):
        val = obj.value
        if isinstance(val, bool | int | float | str):
            return val
        return obj.name

    # dict → recursively normalize
    if isinstance(obj, dict):
        return {str(k): _normalize_for_json(v) for k, v in obj.items()}

    # list/tuple → recursively normalize
    if isinstance(obj, list | tuple):
        return [_normalize_for_json(item) for item in obj]

    # Fallback: convert to repr string with marker
    # This preserves visibility into the data without breaking serialization
    return {"__non_serializable__": True, "type": type(obj).__name__, "repr": repr(obj)}


class Platform(Enum):
    """Supported issue tracking platforms.

    Each platform has a dedicated provider that implements
    the IssueTrackerProvider interface.
    """

    JIRA = auto()
    GITHUB = auto()
    LINEAR = auto()
    AZURE_DEVOPS = auto()
    MONDAY = auto()
    TRELLO = auto()


class TicketStatus(Enum):
    """Normalized ticket statuses across platforms.

    Providers map their platform-specific statuses to these
    normalized values for consistent workflow handling.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    CLOSED = "closed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class TicketType(Enum):
    """Normalized ticket types across platforms.

    Used for downstream automation such as generating semantic branch names
    (e.g., feat/, fix/, chore/) and categorizing work items.
    """

    FEATURE = "feature"  # New functionality, user stories, enhancements
    BUG = "bug"  # Defects, issues, fixes
    TASK = "task"  # General tasks, chores, housekeeping
    MAINTENANCE = "maintenance"  # Tech debt, refactoring, infrastructure
    UNKNOWN = "unknown"  # Unable to determine type


class PlatformMetadata(TypedDict, total=False):
    """Type definition for platform-specific metadata fields.

    This TypedDict provides structure for the platform_metadata field in
    GenericTicket. All fields are optional (total=False) as different
    platforms provide different data.

    Common fields across platforms:
        raw_response: The complete raw API response from the platform
        project_key: Project/repository identifier (Jira: PROJECT, GitHub: owner/repo)
        priority: Platform-specific priority value
        epic_link: Parent epic/feature link (Jira, Linear)
        sprint: Sprint/iteration information
        story_points: Estimation value (Jira, Linear)
        milestone: Milestone/release information (GitHub)
        components: List of component names (Jira)

    Platform-specific fields:
        Jira:
            issue_type_id: Jira issue type ID
            resolution: Resolution status
            fix_versions: Target release versions
        GitHub:
            repository: Full repository name (owner/repo)
            issue_number: Numeric issue/PR number
            is_pull_request: Whether this is a PR vs issue
            state_reason: Reason for closure (completed, not_planned, etc.)
        Linear:
            team_key: Linear team identifier (e.g., "ENG")
            team_name: Linear team display name (e.g., "Engineering")
            cycle: Current cycle/sprint name (or None if not in a cycle)
            parent_id: Parent issue ID for sub-issues (or None)
            linear_uuid: Linear internal UUID for the issue
            priority_value: Numeric priority (0-4, where 0=no priority, 1=urgent)
            state_name: Display name of the workflow state (e.g., "In Progress")
            state_type: Workflow state type (backlog/unstarted/started/completed/canceled)
        Azure DevOps:
            organization: Azure DevOps organization name
            project: Azure DevOps project name
            work_item_type: Azure work item type
            area_path: Area classification
            iteration_path: Iteration/sprint path
            assigned_to_email: Assignee email address
            revision: Work item revision number
        Monday:
            board_id: Monday.com board ID
            board_name: Monday.com board name
            group_title: Group/section title
            creator_name: Item creator name
            status_label: Raw status label from Monday
            account_slug: Monday.com account subdomain
        Trello:
            board_id: Trello board ID
            board_name: Trello board name
            list_id: Trello list ID
            list_name: Trello list name
            due_date: Card due date
            due_complete: Whether due date is marked complete
            is_closed: Whether card is archived/closed
            short_link: Trello short link identifier
    """

    # Common fields
    raw_response: dict[str, Any]
    project_key: str
    priority_label: str
    epic_link: str
    sprint: str
    story_points: float
    milestone: str
    components: list[str]

    # Jira-specific
    issue_type_id: str
    resolution: str
    fix_versions: list[str]
    api_url: str  # The raw API URL (e.g., self link from Jira)
    adf_description: dict[str, Any]  # Atlassian Document Format description

    # GitHub-specific
    repository: str
    issue_number: int
    is_pull_request: bool
    state_reason: str
    author: str

    # Linear-specific
    team_key: str
    team_name: str
    cycle: str | None
    parent_id: str | None
    linear_uuid: str
    priority_value: int | None
    state_name: str
    state_type: str

    # Azure DevOps-specific
    organization: str
    project: str
    work_item_type: str
    area_path: str
    iteration_path: str
    assigned_to_email: str
    revision: int | None

    # Monday-specific
    board_id: str
    board_name: str
    group_title: str
    creator_name: str
    status_label: str
    account_slug: str | None

    # Trello-specific
    list_id: str
    list_name: str
    due_date: str | None
    due_complete: bool
    is_closed: bool
    short_link: str


@dataclass
class GenericTicket:
    """Platform-agnostic ticket representation.

    This is the normalized data model that all platform providers
    must populate. The workflow engine only interacts with this model.

    Attributes:
        id: Unique ticket identifier (platform-specific format preserved)
        platform: Source platform
        url: Original full URL to the ticket
        title: Ticket title/summary
        description: Full description/body text
        status: Normalized status
        type: Normalized ticket type (feature, bug, task, etc.)
        assignee: Assigned user (display name or username)
        labels: List of labels/tags
        created_at: Creation timestamp
        updated_at: Last update timestamp
        branch_summary: Short summary suitable for git branch name
        full_info: Complete raw ticket information for context
        platform_metadata: Platform-specific fields for edge cases.
            See PlatformMetadata TypedDict for expected structure.
            Providers should populate relevant fields based on their platform.
    """

    # Core identifiers
    id: str
    platform: Platform
    url: str

    # Primary fields
    title: str = ""
    description: str = ""
    status: TicketStatus = TicketStatus.UNKNOWN
    type: TicketType = TicketType.UNKNOWN

    # Assignment
    assignee: str | None = None

    # Categorization
    labels: list[str] = field(default_factory=list)

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Workflow fields
    branch_summary: str = ""
    full_info: str = ""

    # Platform-specific raw data (see PlatformMetadata for structure)
    platform_metadata: PlatformMetadata = field(default_factory=dict)  # type: ignore[assignment]

    @property
    def display_id(self) -> str:
        """Human-readable ticket ID for display."""
        return self.id

    @property
    def semantic_branch_prefix(self) -> str:
        """Get semantic branch prefix based on ticket type.

        Returns:
            Conventional prefix for git branch naming following
            conventional commits style.
        """
        prefix_map = {
            TicketType.FEATURE: "feat",
            TicketType.BUG: "fix",
            TicketType.TASK: "chore",
            TicketType.MAINTENANCE: "refactor",
            TicketType.UNKNOWN: "feature",
        }
        return prefix_map.get(self.type, "feature")

    # Default max length for branch summary (same as sanitize_title_for_branch)
    _BRANCH_SUMMARY_MAX_LENGTH: ClassVar[int] = 50

    # Default fallback summary when ticket ID/title sanitize to empty strings
    _FALLBACK_SUMMARY: ClassVar[str] = "unnamed-ticket"

    @property
    def branch_slug(self) -> str:
        """Generate safe git branch slug from ticket (without prefix).

        Returns ONLY the sanitized slug component (e.g., 'test-123-my-feature')
        without any semantic prefix like 'feature/'. The calling code
        (e.g., WorkflowRunner) is responsible for prepending the prefix.

        Handles edge cases:
        - GitHub-style IDs like 'owner/repo#42'
        - Special characters (/, spaces, :, etc.)
        - Disallowed git sequences (.., @{, trailing /, .lock suffix)
        - Empty branch_summary (generates from title)
        - Empty sanitized ticket ID (uses deterministic fallback)
        - Empty sanitized summary (uses 'unnamed-ticket' fallback)
        - Long branch_summary (truncated to max 50 chars)

        Output is deterministic, lowercase, and contains only git-safe
        characters: [a-z0-9-] (no slashes in the slug itself).

        Guarantees:
        - Always has format: id or id-summary
        - Maximum summary length is enforced
        - Always produces a valid, non-empty slug

        Returns:
            Git-compatible branch slug like 'proj-123-add-user-login'
        """
        # Sanitize ticket ID using shared sanitizer (ensures [a-z0-9-] only)
        safe_id = sanitize_for_branch_component(self.id)

        # Handle empty sanitized ID (e.g., ticket ID was only emojis/special chars)
        if not safe_id:
            safe_id = self._generate_fallback_id()

        # Use branch_summary if available, otherwise generate from title
        summary = self.branch_summary
        if summary:
            # Apply max length limit to user-provided summary
            safe_summary = sanitize_title_for_branch(
                summary, max_length=self._BRANCH_SUMMARY_MAX_LENGTH
            )
        elif self.title:
            safe_summary = sanitize_title_for_branch(self.title)
        else:
            safe_summary = ""

        # Handle edge case where summary sanitizes to empty string
        # (e.g., title/summary contained only emojis or special characters)
        if not safe_summary and (self.branch_summary or self.title):
            # Original had content but it all got stripped - use fallback
            safe_summary = self._FALLBACK_SUMMARY

        # Build branch slug (no prefix)
        if safe_summary:
            slug = f"{safe_id}-{safe_summary}"
        else:
            slug = safe_id

        # Final safety checks for git ref requirements (without prefix)
        return self._finalize_git_ref(slug)

    # Windows reserved names (case-insensitive)
    _WINDOWS_RESERVED_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
    )

    # Maximum length for filename stems (prevents MAX_PATH issues)
    _MAX_FILENAME_STEM_LENGTH: ClassVar[int] = 64

    @property
    def safe_filename_stem(self) -> str:
        """Generate filesystem-safe stem from ticket ID.

        Strictly sanitizes the ticket ID for safe use in filenames and
        directory paths. Replaces unsafe characters (/, \\, #, spaces,
        and other problematic chars) with underscores or hyphens.

        This is CRITICAL for security: ticket IDs from platforms like
        GitHub can contain path-traversal characters (e.g., 'owner/repo#1').

        Windows-safety features:
        - Reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) are prefixed
        - Trailing dots and spaces are stripped (cause issues on Windows)
        - Length is truncated to 64 characters (prevents MAX_PATH issues)

        Returns:
            Filesystem-safe string like 'owner_repo_1' or 'TEST-123'
        """
        if not self.id:
            return "unknown-ticket"

        # Replace path separators and other unsafe filesystem characters
        # with underscores for maximum compatibility
        result = self.id
        # Replace forward/back slashes (path traversal risk)
        result = result.replace("/", "_")
        result = result.replace("\\", "_")
        # Replace hash (GitHub issue syntax, shell comment)
        result = result.replace("#", "_")
        # Replace spaces
        result = result.replace(" ", "_")
        # Replace other problematic characters
        for char in [":", "*", "?", '"', "<", ">", "|"]:
            result = result.replace(char, "_")

        # Collapse multiple underscores (using pre-compiled pattern for performance)
        result = _PATTERN_MULTIPLE_UNDERSCORES.sub("_", result)

        # Strip leading/trailing dots, spaces, and underscores aggressively
        # (leading dots are dangerous on some systems - hidden files)
        result = result.strip(" ._")

        # Handle empty result
        if not result:
            return "unknown-ticket"

        # Check for Windows reserved names (case-insensitive)
        if result.upper() in self._WINDOWS_RESERVED_NAMES:
            result = f"ticket_{result}"

        # Truncate to maximum length
        if len(result) > self._MAX_FILENAME_STEM_LENGTH:
            result = result[: self._MAX_FILENAME_STEM_LENGTH]
            # Ensure truncation didn't leave trailing underscores/dots/spaces
            result = result.rstrip("_. ")

        # Final safety check for empty result after all processing
        if not result:
            return "unknown-ticket"

        return result

    def _generate_fallback_id(self) -> str:
        """Generate a deterministic fallback ID when sanitized ticket ID is empty.

        Uses a short hash of the original ticket ID to maintain determinism
        and avoid collisions.

        Returns:
            Fallback ID string like 'ticket-a1b2c3'
        """
        import hashlib

        # Create deterministic hash from original ID
        id_hash = hashlib.sha256(self.id.encode("utf-8")).hexdigest()[:6]
        return f"ticket-{id_hash}"

    @staticmethod
    def _finalize_git_ref(branch: str) -> str:
        """Apply final git ref safety rules.

        Handles sequences that are invalid in git refs even when individual
        characters are valid: consecutive dots, @{ sequences, .lock suffix,
        trailing slashes.

        Args:
            branch: Branch name to finalize

        Returns:
            Git-safe branch name
        """
        # Remove disallowed sequences (these can't appear with new sanitizer
        # but kept for safety)
        branch = branch.replace("..", "-")
        branch = branch.replace("@{", "-")

        # Remove trailing slash
        branch = branch.rstrip("/")

        # Remove .lock suffix
        if branch.endswith(".lock"):
            branch = branch[:-5]

        # Collapse any consecutive hyphens created by replacements
        # (using pre-compiled pattern for performance)
        branch = _PATTERN_MULTIPLE_HYPHENS.sub("-", branch)

        # Strip any trailing hyphens that might result
        branch = branch.rstrip("-")

        return branch

    def to_dict(self) -> dict[str, Any]:
        """Serialize GenericTicket to JSON-compatible dictionary."""
        from dataclasses import asdict

        result = asdict(self)

        result["platform"] = self.platform.name

        result["status"] = self.status.value
        result["type"] = self.type.value

        if self.created_at is not None:
            result["created_at"] = self.created_at.isoformat()
        if self.updated_at is not None:
            result["updated_at"] = self.updated_at.isoformat()

        if result.get("platform_metadata"):
            result["platform_metadata"] = _normalize_for_json(result["platform_metadata"])

        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenericTicket:
        """Deserialize GenericTicket from a dictionary.

        Converts a dictionary (e.g., from JSON storage) back to a GenericTicket.
        Uses resilient deserialization for enums - if a stored value doesn't
        match a current enum member, falls back to UNKNOWN to prevent crashes
        from stale cache entries.

        Args:
            data: Dictionary containing ticket data

        Returns:
            Reconstructed GenericTicket instance

        Raises:
            KeyError: If required fields are missing from data
            ValueError: If platform string is unknown/invalid (prevents data corruption)
        """
        # Make a copy to avoid mutating the input
        ticket_data = data.copy()

        # Normalize platform casing ("jira" → Platform.JIRA)
        platform_str = ticket_data.get("platform", "")
        platform_normalized = platform_str.upper() if platform_str else ""
        if not hasattr(Platform, platform_normalized):
            raise ValueError(f"Unknown platform: {platform_str!r}")
        ticket_data["platform"] = Platform[platform_normalized]

        # Resilient TicketStatus enum conversion
        status_str = ticket_data.get("status", "unknown")
        try:
            ticket_data["status"] = TicketStatus(status_str)
        except ValueError:
            # Fallback for unknown status values (stale cache)
            ticket_data["status"] = TicketStatus.UNKNOWN

        # Resilient TicketType enum conversion
        type_str = ticket_data.get("type", "unknown")
        try:
            ticket_data["type"] = TicketType(type_str)
        except ValueError:
            # Fallback for unknown type values (stale cache)
            ticket_data["type"] = TicketType.UNKNOWN

        # Convert ISO format strings back to datetime
        created_at = ticket_data.get("created_at")
        if created_at and isinstance(created_at, str):
            try:
                ticket_data["created_at"] = datetime.fromisoformat(created_at)
            except ValueError:
                ticket_data["created_at"] = None
        elif created_at is None:
            ticket_data["created_at"] = None

        updated_at = ticket_data.get("updated_at")
        if updated_at and isinstance(updated_at, str):
            try:
                ticket_data["updated_at"] = datetime.fromisoformat(updated_at)
            except ValueError:
                ticket_data["updated_at"] = None
        elif updated_at is None:
            ticket_data["updated_at"] = None

        # Ensure labels is a list
        if "labels" in ticket_data and ticket_data["labels"] is None:
            ticket_data["labels"] = []

        # Ensure platform_metadata is a dict
        if "platform_metadata" in ticket_data and ticket_data["platform_metadata"] is None:
            ticket_data["platform_metadata"] = {}

        return cls(**ticket_data)

    @classmethod
    def from_jira(cls, jira_ticket: JiraTicket) -> GenericTicket:
        """Create GenericTicket from a legacy JiraTicket.

        This factory method encapsulates the mapping logic from the legacy
        JiraTicket dataclass to GenericTicket. Use this instead of manually
        constructing GenericTicket from JiraTicket fields.

        Args:
            jira_ticket: JiraTicket instance from ingot.integrations.jira

        Returns:
            GenericTicket with fields mapped from JiraTicket
        """
        return cls(
            id=jira_ticket.ticket_id,
            platform=Platform.JIRA,
            url=jira_ticket.ticket_url,
            title=jira_ticket.title,
            description=jira_ticket.description,
            branch_summary=jira_ticket.summary,
            full_info=jira_ticket.full_info,
        )


class IssueTrackerProvider(ABC):
    """Abstract base class for issue tracker integrations.

    All platform-specific providers must implement this interface.
    This ensures consistent behavior and enables the Open/Closed principle.

    Providers should:
    - Handle all platform-specific API communication
    - Map platform statuses to TicketStatus enum
    - Map platform types to TicketType enum
    - Never call print() or input() directly (use UserInteractionInterface)

    Constructor Contract:
        Provider ``__init__`` methods must be compatible with ProviderRegistry
        instantiation. The registry uses runtime inspection to inject dependencies.
        Valid constructor signatures:

        1. No required arguments (recommended for simple providers)::

            def __init__(self):
                self._session = None

        2. Optional ``user_interaction`` parameter for DI::

            def __init__(self, user_interaction: UserInteractionInterface | None = None):
                self.user_interaction = user_interaction or CLIUserInteraction()

        The registry will automatically inject ``UserInteractionInterface`` if the
        parameter exists. Providers with other required parameters will fail
        instantiation with a ``TypeError``.

    Class Attributes:
        PLATFORM: Required class attribute of type ``Platform`` for registry
            registration. Must be set before using ``@ProviderRegistry.register``.

    Utility Methods:
        safe_nested_get: Static helper for defensive access to nested dict fields.
            Use this in normalize() implementations to handle malformed API responses
            where nested objects may be None or non-dict types.
    """

    @staticmethod
    def safe_nested_get(obj: Any, key: str, default: str = "") -> str:
        """Safely get a nested key from an object that might not be a dict.

        This helper is designed for defensive normalization of API responses
        where nested fields (like status, assignee, project) may be None or
        unexpected types instead of the expected dict structure.

        Example usage in normalize()::

            status_obj = fields.get("status")
            status_name = self.safe_nested_get(status_obj, "name", "")

            # Instead of risky chained access:
            # status_name = fields.get("status", {}).get("name", "")
            # which fails if status is None (not a dict)

        Args:
            obj: The object to get the key from (may be None, dict, or other type)
            key: The key to retrieve
            default: Default value if key not found or obj is not a dict

        Returns:
            The string value at key if obj is a dict and key exists,
            otherwise the default value. Non-string values are converted to str.
        """
        if isinstance(obj, dict):
            value = obj.get(key, default)
            return str(value) if value is not None else default
        return default

    @staticmethod
    def parse_timestamp(timestamp_str: str | None) -> datetime | None:
        """Parse ISO timestamp from platform API response.

        This is a shared utility method for parsing ISO 8601 timestamps
        commonly returned by issue tracker APIs. Handles both 'Z' suffix
        and explicit timezone offsets.

        Args:
            timestamp_str: ISO 8601 timestamp string (e.g., "2024-01-15T10:30:00Z")

        Returns:
            Parsed datetime object with timezone info, or None if parsing fails
            or input is None/empty.
        """
        if not timestamp_str:
            return None
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """Return the platform this provider handles.

        Returns:
            The Platform enum value for this provider
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name.

        Returns:
            Display name like 'Jira', 'GitHub Issues', etc.
        """
        pass

    @abstractmethod
    def can_handle(self, input_str: str) -> bool:
        """Check if this provider can handle the given input.

        Args:
            input_str: URL or ticket ID to check

        Returns:
            True if this provider recognizes the input format
        """
        pass

    @abstractmethod
    def parse_input(self, input_str: str) -> str:
        """Parse input and extract normalized ticket ID.

        Args:
            input_str: URL or ticket ID

        Returns:
            Normalized ticket ID (e.g., "PROJECT-123", "owner/repo#42")

        Raises:
            ValueError: If input cannot be parsed
        """
        pass

    def check_connection(self) -> tuple[bool, str]:
        """Verify the integration is properly configured.

        In the hybrid architecture, connection checking is delegated to
        TicketService via TicketFetcher implementations. This default
        implementation returns a ready status.

        Providers may override this for platform-specific checks.

        Returns:
            Tuple of (success: bool, message: str)
            - success: True if connection works
            - message: Human-readable status message
        """
        return (True, f"{self.__class__.__name__} ready")

    @abstractmethod
    def normalize(self, raw_data: dict[str, Any], ticket_id: str | None = None) -> GenericTicket:
        """Convert raw platform API data to GenericTicket.

        This is the normalization layer that transforms platform-specific
        API responses into the unified GenericTicket format.

        Args:
            raw_data: Raw API response from the platform.
            ticket_id: Optional ticket ID from parse_input(). Some providers
                       (e.g., MondayProvider) need this to extract context
                       like account slug for URL construction.

        Returns:
            Populated GenericTicket with normalized fields.

        Raises:
            ValueError: If required fields are missing from raw_data.
        """
        pass

    def generate_branch_summary(self, ticket: GenericTicket) -> str:
        """Generate a git-friendly branch summary.

        Default implementation - can be overridden by providers
        for platform-specific naming conventions.

        Args:
            ticket: The ticket to generate summary for

        Returns:
            Short lowercase hyphenated summary (max 50 chars)
        """
        return sanitize_title_for_branch(ticket.title)
