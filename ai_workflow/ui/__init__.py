"""UI components for AI Workflow.

This package contains:
- prompts: Questionary-based user input prompts
- menus: Interactive menu functions
- log_buffer: Memory-efficient log buffer with file backing
- plan_tui: TUI for plan generation (Step 1)
"""

from ai_workflow.ui.log_buffer import TaskLogBuffer
from ai_workflow.ui.menus import (
    MainMenuChoice,
    TaskReviewChoice,
    show_git_dirty_menu,
    show_main_menu,
    show_model_selection,
    show_task_checkboxes,
    show_task_review_menu,
)
from ai_workflow.ui.plan_tui import PlanGeneratorUI
from ai_workflow.ui.prompts import (
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
    # Plan TUI
    "PlanGeneratorUI",
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

