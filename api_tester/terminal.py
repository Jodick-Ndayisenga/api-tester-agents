"""Shared Rich terminal configuration.

Keeping one configured console prevents different modules from choosing
different colors, wrapping, or terminal-detection behavior. Rich still
automatically disables color when output is redirected or the terminal does
not support it.
"""

from __future__ import annotations

from rich.console import Console
from rich.traceback import install as install_rich_traceback


console = Console(
    highlight=False,
    soft_wrap=True,
    markup=True,
)


def configure_terminal() -> None:
    """Install concise Rich tracebacks for the command-line application."""
    install_rich_traceback(show_locals=False, max_frames=20)
