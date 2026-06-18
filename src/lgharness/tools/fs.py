"""Filesystem tools."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool


@tool
async def read_file(path: str) -> str:
    """Read a UTF-8 text file from the local filesystem and return its contents."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"File not found: {p}"
    if p.is_dir():
        return f"Cannot read a directory: {p}"
    return p.read_text(encoding="utf-8", errors="replace")


@tool
async def write_file(path: str, content: str) -> str:
    """Write text content to a file, overwriting any existing file."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p}"
