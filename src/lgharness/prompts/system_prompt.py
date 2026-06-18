"""System prompt assembly."""

from __future__ import annotations


def build_system_prompt(cwd: str) -> str:
    """Return the system prompt for a harness session."""
    return (
        "You are a coding assistant operating in a terminal.\n"
        f"Current working directory: {cwd}\n\n"
        "You have these tools:\n"
        "- read_file(path): read a text file.\n"
        "- write_file(path, content): create or overwrite a file.\n"
        "- bash(command): run a shell command.\n\n"
        "Use tools when they help. Prefer reading before writing. "
        "Keep responses concise."
    )
