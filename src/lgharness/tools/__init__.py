"""Tool registry for the harness."""

from __future__ import annotations

from lgharness.tools.fs import read_file, write_file
from lgharness.tools.shell import bash

DEFAULT_TOOLS = [read_file, write_file, bash]
TOOLS_BY_NAME = {t.name: t for t in DEFAULT_TOOLS}

__all__ = ["DEFAULT_TOOLS", "TOOLS_BY_NAME", "read_file", "write_file", "bash"]
