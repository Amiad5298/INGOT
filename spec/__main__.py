"""Entry point for running spec as a module.

This allows running the application with:
    python -m spec [OPTIONS] [TICKET]
"""

from spec.cli import app

if __name__ == "__main__":
    app()

