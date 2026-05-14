from __future__ import annotations

from typing import Annotated

import typer
from rich.panel import Panel

from app.config import get_settings
from app.utils.logger import configure_logging, get_console, get_logger


def main(
    task: Annotated[
        str | None,
        typer.Argument(help="One-line task for the future browser agent."),
    ] = None,
) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    console = get_console()
    logger = get_logger(__name__)

    console.rule(settings.app_name)
    console.print(
        Panel.fit(
            "Hello. browser_ai_agent CLI is ready.",
            title="Welcome",
            border_style="cyan",
        )
    )

    user_task = (task or typer.prompt("Enter one-line task")).strip()
    if not user_task:
        console.print("[bold red]Task is empty.[/bold red]")
        raise typer.Exit(code=1)

    logger.info("Task accepted")
    console.print(f"[bold]You:[/bold] {user_task}")
    console.print(
        "[dim]Playwright and Claude are not connected in this stage.[/dim]"
    )


def cli() -> None:
    typer.run(main)


if __name__ == "__main__":
    cli()
