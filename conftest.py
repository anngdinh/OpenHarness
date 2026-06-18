"""Ensure this worktree's ``src`` is imported in preference to any editable install.

The repo is installed editable from the primary checkout, so its ``.pth`` points at
that checkout's ``src`` — which does not contain packages created inside a worktree
(e.g. ``lgharness``). Prepend this worktree's ``src`` so tests exercise local code.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str(Path(__file__).parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
