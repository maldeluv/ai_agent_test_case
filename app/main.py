from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from app.agent.loop import MainAgentLoop
from app.browser.session import BrowserSession
from app.config import get_settings
from app.tools import create_default_tool_registry
from app.utils.logger import configure_logging, get_console, get_logger


async def run_cli(task: str, wait_for_exit: bool) -> None:
    settings = get_settings()
    console = get_console()
    logger = get_logger(__name__)
    browser = BrowserSession(settings)
    tool_registry = create_default_tool_registry()

    try:
        page = await browser.start()
        logger.info("Browser session started")

        status = Table.grid(padding=(0, 1))
        status.add_column(style="bold")
        status.add_column()
        status.add_row("Profile", str(browser.profile_dir))
        status.add_row(
            "Viewport",
            f"{settings.viewport_width}x{settings.viewport_height}",
        )
        status.add_row("Page", page.url)
        status.add_row("Tools", str(len(tool_registry.list_tools())))

        console.print(
            Panel(
                status,
                title="Browser Profile Loaded",
                border_style="green",
            )
        )
        console.print(f"[bold]You:[/bold] {task}")

        if settings.anthropic_api_key is None:
            console.print(
                "[yellow]ANTHROPIC_API_KEY is not configured. "
                "Browser started, but the agent loop was not run.[/yellow]"
            )
        else:
            agent = MainAgentLoop(
                settings=settings,
                browser=browser,
                registry=tool_registry,
                console=console,
            )
            result = await agent.run(task)
            console.print(
                Panel.fit(
                    f"{result.summary}\n\nStatus: {result.status}\nSteps: {result.steps_used}",
                    title="Final Report",
                    border_style="green" if result.status == "success" else "yellow",
                )
            )

        if wait_for_exit:
            try:
                console.input("[bold]Press Enter to close the browser...[/bold]")
            except EOFError:
                logger.info("Input stream closed; shutting down browser session")
    finally:
        await browser.close()
        logger.info("Browser session closed")


def main(
    task: Annotated[
        str | None,
        typer.Argument(help="One-line task for the future browser agent."),
    ] = None,
    wait_for_exit: Annotated[
        bool,
        typer.Option(
            "--wait/--no-wait",
            help="Keep the browser open until Enter is pressed.",
        ),
    ] = True,
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
    try:
        asyncio.run(run_cli(user_task, wait_for_exit))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")


def cli() -> None:
    typer.run(main)


if __name__ == "__main__":
    cli()
