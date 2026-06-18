"""Shell tool."""

from __future__ import annotations

import asyncio

from langchain_core.tools import tool

_TIMEOUT_SECONDS = 60


@tool
async def bash(command: str) -> str:
    """Run a shell command and return combined stdout/stderr output."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        return f"Command timed out after {_TIMEOUT_SECONDS}s"
    text = stdout.decode("utf-8", errors="replace")
    return text if text.strip() else f"(no output, exit code {proc.returncode})"
