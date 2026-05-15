from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from app.agent.loop import MainAgentLoop
from app.agent.schemas import AgentRunResult
from app.browser.session import BrowserSession
from app.config import get_settings
from app.tools import create_default_tool_registry
from app.utils.logger import configure_logging, get_console, get_logger


def compose_session_task(
    *,
    current_message: str,
    session_history: list[tuple[str, AgentRunResult]],
) -> str:
    if not session_history:
        return current_message

    history_lines = []
    for index, (user_message, result) in enumerate(session_history[-5:], start=1):
        history_lines.append(
            (
                f"{index}. User asked: {user_message}\n"
                f"   Agent status: {result.status}; summary: {result.summary}"
            )
        )
        if result.debug_context:
            history_lines.append(f"   Debug context: {result.debug_context}")

    return (
        "This is a continuation in the same open browser session.\n"
        "Use the current browser state as the source of truth. The user may be "
        "refining, correcting, approving, or extending the previous task.\n\n"
        "Recent session history:\n"
        f"{chr(10).join(history_lines)}\n\n"
        "Current user message:\n"
        f"{current_message}"
    )


async def run_cli(task: str, wait_for_exit: bool, interactive: bool) -> None:
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

        if not settings.has_active_llm_api_key():
            console.print(
                f"[yellow]{settings.llm_provider.upper()} API key is not configured. "
                "Browser started, but the agent loop was not run.[/yellow]"
            )
        else:
            current_message: str | None = task
            session_history: list[tuple[str, AgentRunResult]] = []
            while current_message:
                console.print(f"[bold]You:[/bold] {current_message}")
                agent = MainAgentLoop(
                    settings=settings,
                    browser=browser,
                    registry=tool_registry,
                    console=console,
                )
                effective_task = compose_session_task(
                    current_message=current_message,
                    session_history=session_history,
                )
                result = await agent.run(effective_task)
                session_history.append((current_message, result))
                console.print(
                    Panel.fit(
                        f"{result.summary}\n\nStatus: {result.status}\nSteps: {result.steps_used}",
                        title="Final Report",
                        border_style="green" if result.status == "success" else "yellow",
                    )
                )

                if not interactive or not wait_for_exit:
                    break

                try:
                    next_message = console.input(
                        "\n[bold cyan]You[/bold cyan] "
                        "[dim](new task / clarification / approval, Enter to close):[/dim] "
                    )
                except EOFError:
                    logger.info("Input stream closed; shutting down browser session")
                    break

                current_message = next_message.strip() or None

        if wait_for_exit and (not settings.has_active_llm_api_key() or not interactive):
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
            help="Keep the browser open for follow-up input or final Enter.",
        ),
    ] = True,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive/--one-shot",
            help="Allow follow-up messages in the same browser session.",
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
        asyncio.run(run_cli(user_task, wait_for_exit, interactive))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")


def cli() -> None:
    typer.run(main)


if __name__ == "__main__":
    cli()
