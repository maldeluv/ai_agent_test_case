from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler


_CONSOLE = Console()
_LOGGER_CONFIGURED = False


def get_console() -> Console:
    return _CONSOLE


def configure_logging(level: str = "INFO") -> None:
    global _LOGGER_CONFIGURED

    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if _LOGGER_CONFIGURED:
        for handler in root_logger.handlers:
            handler.setLevel(log_level)
        return

    handler = RichHandler(
        console=_CONSOLE,
        rich_tracebacks=True,
        show_path=False,
        show_time=True,
    )
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    _LOGGER_CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(name or "browser_ai_agent")
