"""Workflow implementation for SPEC.

This package contains:
- state: WorkflowState dataclass
- tasks: Task parsing and management
- task_memory: Cross-task learning system
- events: Task execution events and run records for TUI
- step1_plan: Step 1 - Create implementation plan
- step2_tasklist: Step 2 - Create task list
- step3_execute: Step 3 - Execute clean loop
- runner: Workflow orchestration
"""

from spec.workflow.events import (
    TaskEvent,
    TaskEventCallback,
    TaskEventType,
    TaskRunRecord,
    TaskRunStatus,
    create_run_finished_event,
    create_run_started_event,
    create_task_finished_event,
    create_task_output_event,
    create_task_started_event,
    format_log_filename,
    format_run_directory,
    format_timestamp,
    slugify_task_name,
)
from spec.workflow.runner import run_spec_driven_workflow, workflow_cleanup
from spec.workflow.state import WorkflowState
from spec.workflow.step1_plan import step_1_create_plan
from spec.workflow.step2_tasklist import step_2_create_tasklist
from spec.workflow.step3_execute import step_3_execute
from spec.workflow.task_memory import (
    TaskMemory,
    build_pattern_context,
    capture_task_memory,
    find_related_task_memories,
)
from spec.workflow.tasks import (
    Task,
    TaskCategory,
    TaskStatus,
    format_task_list,
    get_completed_tasks,
    get_pending_tasks,
    mark_task_complete,
    parse_task_list,
)

__all__ = [
    # State
    "WorkflowState",
    # Tasks
    "Task",
    "TaskCategory",
    "TaskStatus",
    "parse_task_list",
    "get_pending_tasks",
    "get_completed_tasks",
    "mark_task_complete",
    "format_task_list",
    # Task Memory
    "TaskMemory",
    "capture_task_memory",
    "find_related_task_memories",
    "build_pattern_context",
    # Events
    "TaskEventType",
    "TaskEvent",
    "TaskEventCallback",
    "TaskRunStatus",
    "TaskRunRecord",
    "slugify_task_name",
    "format_log_filename",
    "format_timestamp",
    "format_run_directory",
    "create_run_started_event",
    "create_task_started_event",
    "create_task_output_event",
    "create_task_finished_event",
    "create_run_finished_event",
    # Steps
    "step_1_create_plan",
    "step_2_create_tasklist",
    "step_3_execute",
    # Runner
    "run_spec_driven_workflow",
    "workflow_cleanup",
]

