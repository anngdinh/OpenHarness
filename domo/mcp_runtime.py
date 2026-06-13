"""Generate a runtime plugin holding datasource HTTP MCP config from env.

Secrets are read from the environment at startup and written into a throwaway
plugin directory passed to build_runtime via extra_plugin_roots — they are
never baked into the repo.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from domo.config import DomoConfig

log = logging.getLogger(__name__)


def write_runtime_mcp_plugin(config: DomoConfig, dest: str | Path) -> Path | None:
    """Write a plugin (plugin.json + .mcp.json) for the configured datasources.

    Returns the plugin directory, or None when there are no datasources.
    A datasource whose ``token_env`` is set but missing from the environment is
    skipped (with a warning) rather than emitting an unauthenticated server.
    """
    if not config.datasources:
        return None

    servers: dict[str, dict] = {}
    for ds in config.datasources:
        headers: dict[str, str] = {}
        if ds.token_env:
            token = os.environ.get(ds.token_env)
            if not token:
                log.warning("datasource %s skipped: env %s not set", ds.name, ds.token_env)
                continue
            headers["Authorization"] = f"Bearer {token}"
        servers[ds.name] = {"type": "http", "url": ds.url, "headers": headers}

    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    (dest_path / "plugin.json").write_text(
        json.dumps(
            {"name": "domo-datasources", "version": "0.1.0", "description": "Runtime datasource MCPs."},
            indent=2,
        ),
        encoding="utf-8",
    )
    (dest_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": servers}, indent=2), encoding="utf-8"
    )
    return dest_path
