"""UI components for SPEC.

This package contains:
- prompts: Questionary-based user input prompts
- menus: Interactive menu functions
- log_buffer: Memory-efficient log buffer with file backing
- plan_tui: StreamingOperationUI for single long-running operations
"""

from spec.ui.log_buffer import TaskLogBuffer
from spec.ui.menus import (
    MainMenuChoice,
    TaskReviewChoice,
    show_git_dirty_menu,
    show_main_menu,
    show_model_selection,
    show_task_checkboxes,
    show_task_review_menu,
)
from spec.ui.plan_tui import StreamingOperationUI
from spec.ui.prompts import (
    custom_style,
    prompt_checkbox,
    prompt_confirm,
    prompt_enter,
    prompt_input,
    prompt_select,
)

__all__ = [
    # Log Buffer
    "TaskLogBuffer",
    # Streaming Operation TUI
    "StreamingOperationUI",
    # Prompts
    "custom_style",
    "prompt_checkbox",
    "prompt_confirm",
    "prompt_enter",
    "prompt_input",
    "prompt_select",
    # Menus
    "MainMenuChoice",
    "TaskReviewChoice",
    "show_main_menu",
    "show_task_review_menu",
    "show_git_dirty_menu",
    "show_model_selection",
    "show_task_checkboxes",
]

