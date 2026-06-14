"""Build a per-conversation QueryEngine for the domo agent."""

from __future__ import annotations

import atexit
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import domo
from openharness.engine.query_engine import QueryEngine
from openharness.permissions.checker import PermissionChecker
from openharness.ui.runtime import build_runtime

from domo.config import DomoConfig
from domo.mcp_runtime import write_runtime_mcp_plugin
from domo.persona import PERSONA


def _skills_plugin_root() -> str:
    return str(Path(domo.__file__).parent / "plugin")


# domo is a read-only domain assistant: it only needs the shell (kubectl, etc.),
# its product skills, and the configured datasource MCP tools. Every other
# built-in tool (file edit/write, task/agent/team orchestration, web, cron, …)
# is removed so the model never sees it.
_KEEP_TOOL_NAMES = frozenset({"bash", "skill"})


def _is_allowed_tool(name: str) -> bool:
    return name in _KEEP_TOOL_NAMES or name.startswith("mcp__")


def make_build_engine(
    config: DomoConfig, api_client=None
) -> Callable[[str], Awaitable[QueryEngine]]:
    """Return an async factory: contextId -> a configured QueryEngine.

    Each conversation (A2A contextId) gets its own engine with the domo persona,
    the bundled skills plugin, the runtime datasource MCP plugin, a read-mostly
    permission policy, and session memory keyed by the contextId.
    """
    plugin_roots: list[str] = [_skills_plugin_root()]
    mcp_dir = Path(tempfile.mkdtemp(prefix="domo-mcp-"))
    atexit.register(shutil.rmtree, mcp_dir, ignore_errors=True)
    mcp_root = write_runtime_mcp_plugin(config, mcp_dir)
    if mcp_root is not None:
        plugin_roots.append(str(mcp_root))

    async def build_engine(context_id: str) -> QueryEngine:
        bundle = await build_runtime(
            system_prompt=PERSONA,
            cwd=config.cwd,
            model=config.model,
            api_client=api_client,
            extra_plugin_roots=plugin_roots,
            ask_user_prompt=None,
            enforce_max_turns=True,
        )
        # bundle.session_id is intentionally unused here: the engine reads
        # tool_metadata["session_id"] for session memory, and the A2A path does
        # not use handle_line snapshot persistence.
        engine = bundle.engine
        # Restrict the toolset to bash + skills + MCP tools (the engine shares
        # this exact registry, so removed tools are never exposed to the model).
        for tool in list(bundle.tool_registry.list_tools()):
            if not _is_allowed_tool(tool.name):
                bundle.tool_registry.unregister(tool.name)
        # Per-conversation memory: session memory is keyed by session_id.
        engine.tool_metadata["session_id"] = context_id
        # Read-mostly policy (kubectl mutations denied), applied post-build.
        engine.set_permission_checker(PermissionChecker(config.permission_settings()))
        return engine

    return build_engine
