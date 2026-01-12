"""Entry point for running ai_workflow as a module.

This allows running the application with:
    python -m ai_workflow [OPTIONS] [TICKET]
"""

from ai_workflow.cli import app

if __name__ == "__main__":
    app()

