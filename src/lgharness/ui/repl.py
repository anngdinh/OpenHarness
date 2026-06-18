"""Terminal REPL for the harness."""

from __future__ import annotations

import asyncio

from rich.console import Console

from lgharness.engine.stream_events import (
    AssistantMessage,
    ErrorEvent,
    PermissionRequest,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


def render(event, console: Console) -> None:
    """Render a single stream event to the terminal."""
    if isinstance(event, AssistantMessage):
        console.print(event.text)
    elif isinstance(event, ToolExecutionStarted):
        console.print(f"[dim]→ {event.tool_name}({event.tool_input})[/dim]")
    elif isinstance(event, ToolExecutionCompleted):
        style = "red" if event.is_error else "green"
        console.print(f"[{style}]← {event.output}[/{style}]")
    elif isinstance(event, ErrorEvent):
        console.print(f"[red]error: {event.message}[/red]")


def _ask_permission(request: PermissionRequest, console: Console) -> dict:
    """Prompt for y/n per pending tool call; return id -> approved map."""
    answers: dict = {}
    for req in request.requests:
        console.print(f"[yellow]Permission needed: {req['name']}({req['args']})[/yellow]")
        reply = input("Approve? [y/N] ").strip().lower()
        answers[req["id"]] = reply in {"y", "yes"}
    return answers


async def run_repl(engine) -> None:
    """Run the interactive read-eval-print loop."""
    console = Console()
    console.print("[bold]lgharness[/bold] — type /exit to quit.")
    while True:
        try:
            text = await asyncio.to_thread(input, "› ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if text.strip() in {"/exit", "/quit"}:
            return
        if not text.strip():
            continue

        async for event in engine.submit_message(text):
            if isinstance(event, PermissionRequest):
                answers = _ask_permission(event, console)
                async for ev in engine.resume(answers):
                    render(ev, console)
            else:
                render(event, console)
