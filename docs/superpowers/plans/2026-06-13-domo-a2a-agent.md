# domo — Domain Assistant A2A Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `domo`, a standalone domain-assistant agent app exposed over A2A, by reusing the core `openharness.a2a` transport via an injected `build_engine(context_id)` factory.

**Architecture:** A small injection point added to the core A2A transport (`SessionManager`/`build_asgi_app` accept an optional `build_engine` callback; default = current behavior). A new top-level `domo/` package defines the agent: a persona system prompt, a bundled skills plugin (product knowledge), a runtime-generated HTTP datasource MCP plugin (secrets from env), read-mostly kubectl permissions (via `set_permission_checker` post-build), and per-conversation memory keyed by A2A `contextId` (via `engine.tool_metadata["session_id"]`). `domo serve` runs the core A2A server with this factory.

**Tech Stack:** Python 3.10+, a2a-sdk 1.1.0 (optional extra `a2a`, already pinned), pydantic v2, typer, pytest. Reuses `openharness.ui.runtime.build_runtime`, `openharness.a2a.*`, `openharness.permissions`.

---

## Verified core facts (from spike — rely on these)
- `build_runtime(...)` accepts: `system_prompt`, `extra_plugin_roots`, `permission_mode`, `model`, `api_client`, `cwd`, `ask_user_prompt`, `enforce_max_turns`. Returns `RuntimeBundle` with `.engine` (a `QueryEngine`).
- `QueryEngine` has `.tool_metadata` (mutable dict) and `.set_permission_checker(PermissionChecker)`.
- `PermissionMode` values: `default`, `plan`, `full_auto`. `PermissionChecker.evaluate` checks `denied_commands` (fnmatch globs) BEFORE the `full_auto` allow-all → `full_auto` + `denied_commands` = "allow all except denied" (headless read-mostly).
- `PermissionSettings(mode, allowed_tools, denied_tools, path_rules, denied_commands)`.
- Plugin loading: `build_runtime(extra_plugin_roots=[dir])` loads each dir as a plugin (needs `plugin.json`); skills from `skills/` (manifest `skills_dir`), MCP from `mcp.json` or `.mcp.json`. MCP servers namespaced `{plugin.name}:{name}`.
- a2a tests MUST run with: `uv run --extra a2a --extra dev pytest ...`
- `openharness.a2a` import requires the `a2a` extra; in `domo` import it normally (domo always needs the extra).

## ⚠️ GIT SAFETY (every subagent)
On branch `agentbase-harness`. NEVER `git checkout`/`switch`/`reset`/`stash` or change branches. Reviewers inspect via `git show SHA:path` / `git diff A B` only. Implementers only `git add <files>` + `git commit`.

## File structure
```
src/openharness/a2a/sessions.py   # MODIFY: add build_engine param (Task 1)
src/openharness/a2a/server.py     # MODIFY: thread build_engine through build_asgi_app (Task 1)
domo/
  __init__.py
  config.py        # DomoConfig + from_env + permission_settings() (Task 2)
  persona.py       # PERSONA system prompt (Task 3)
  plugin/
    plugin.json
    skills/example-product/SKILL.md   # seed sample (Task 3)
  mcp_runtime.py   # write_runtime_mcp_plugin(config, dest) (Task 4)
  agent.py         # make_build_engine(config, api_client=None) (Task 5)
  cli.py           # `domo serve` / `domo doctor` (Task 6)
pyproject.toml     # MODIFY: domo script + package + (domo needs [a2a]) (Task 6)
tests/test_domo/
  __init__.py
  conftest.py      # reuse FakeStreamingClient (Task 5/7)
  test_config.py   # (Task 2)
  test_mcp_runtime.py  # (Task 4)
  test_agent.py    # (Task 5)
  test_server.py   # integration (Task 7)
Dockerfile.domo    # (Task 8)
docs/domo-deploy.md # (Task 8)
```

---

## Task 1: Core injection — `build_engine` callback

**Files:**
- Modify: `src/openharness/a2a/sessions.py`
- Modify: `src/openharness/a2a/server.py`
- Test: `tests/test_a2a/test_sessions.py` (extend)

- [ ] **Step 1: Write the failing test** — append to `tests/test_a2a/test_sessions.py`:
```python
@pytest.mark.asyncio
async def test_build_engine_callback_is_used(tmp_path, fake_client_factory):
    calls: list[str] = []

    async def fake_build_engine(context_id: str):
        calls.append(context_id)
        from openharness.ui.runtime import build_runtime
        bundle = await build_runtime(
            cwd=str(tmp_path), api_client=fake_client_factory([["hi"]]), enforce_max_turns=True
        )
        return bundle.engine

    mgr = SessionManager(cwd=str(tmp_path), build_engine=fake_build_engine)
    s1 = await mgr.get_or_create("ctx-1")
    s2 = await mgr.get_or_create("ctx-1")
    assert s1.engine is s2.engine
    assert calls == ["ctx-1"]  # built once, via the callback
```

- [ ] **Step 2: Run to verify it fails**

`uv run --extra a2a --extra dev pytest tests/test_a2a/test_sessions.py::test_build_engine_callback_is_used -v` → FAIL (unexpected `build_engine` kwarg)

- [ ] **Step 3: Implement** — edit `src/openharness/a2a/sessions.py`:
Add import: `from collections.abc import Awaitable, Callable`. Change `SessionManager.__init__` to accept and store `build_engine`, and use it in `get_or_create`:
```python
    def __init__(
        self,
        *,
        cwd: str,
        api_client: SupportsStreamingMessages | None = None,
        model: str | None = None,
        permission_mode: str | None = None,
        build_engine: Callable[[str], Awaitable[QueryEngine]] | None = None,
    ) -> None:
        self._cwd = cwd
        self._api_client = api_client
        self._model = model
        self._permission_mode = permission_mode
        self._build_engine = build_engine
        self._sessions: dict[str, A2ASession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, context_id: str) -> A2ASession:
        async with self._lock:
            existing = self._sessions.get(context_id)
            if existing is not None:
                return existing
            if self._build_engine is not None:
                engine = await self._build_engine(context_id)
            else:
                bundle = await build_runtime(
                    cwd=self._cwd,
                    model=self._model,
                    permission_mode=self._permission_mode,
                    api_client=self._api_client,
                    enforce_max_turns=True,
                )
                engine = bundle.engine
            session = A2ASession(context_id=context_id, engine=engine)
            self._sessions[context_id] = session
            return session
```

- [ ] **Step 4: Thread through `build_asgi_app`** — edit `src/openharness/a2a/server.py` `build_asgi_app` signature + SessionManager construction:
Add param `build_engine=None` to `build_asgi_app(...)` and pass it: `SessionManager(cwd=cwd, api_client=api_client, model=model, permission_mode=permission_mode, build_engine=build_engine)`. Also add `build_engine=None` to `run_a2a_server(...)` and forward it to `build_asgi_app`.

- [ ] **Step 5: Run tests**

`uv run --extra a2a --extra dev pytest tests/test_a2a -q` → ALL pass (new test + existing, no regression).

- [ ] **Step 6: Commit**
```bash
git add src/openharness/a2a/sessions.py src/openharness/a2a/server.py tests/test_a2a/test_sessions.py
git commit -m "feat(a2a): allow injecting a build_engine factory into the server"
```

---

## Task 2: `DomoConfig` + permission policy

**Files:**
- Create: `domo/__init__.py` (empty), `domo/config.py`
- Create: `tests/test_domo/__init__.py` (empty), `tests/test_domo/test_config.py`

- [ ] **Step 1: Write the failing test** — `tests/test_domo/test_config.py`:
```python
from openharness.permissions.modes import PermissionMode
from openharness.permissions.checker import PermissionChecker

from domo.config import DomoConfig


def test_defaults():
    c = DomoConfig()
    assert c.model is None
    assert c.datasources == []
    assert c.permission_mode == "full_auto"


def test_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DOMO_MODEL", "gpt-x")
    monkeypatch.setenv("DOMO_CWD", str(tmp_path))
    c = DomoConfig.from_env()
    assert c.model == "gpt-x"
    assert c.cwd == str(tmp_path)


def test_permission_blocks_kubectl_mutations_allows_reads():
    checker = PermissionChecker(DomoConfig().permission_settings())
    assert not checker.evaluate("bash", is_read_only=False, command="kubectl delete pod web").allowed
    assert not checker.evaluate("bash", is_read_only=False, command="kubectl apply -f x.yaml").allowed
    assert not checker.evaluate("bash", is_read_only=False, command="sudo reboot").allowed
    assert checker.evaluate("bash", is_read_only=False, command="kubectl get pods").allowed
    assert checker.evaluate("bash", is_read_only=False, command="kubectl describe pod web").allowed


def test_permission_mode_is_full_auto():
    assert DomoConfig().permission_settings().mode == PermissionMode.FULL_AUTO
```

- [ ] **Step 2: Run to verify it fails**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_config.py -v` → FAIL (ModuleNotFoundError: domo)

- [ ] **Step 3: Implement** — `domo/config.py`:
```python
"""Configuration for the domo domain-assistant agent."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from openharness.config.settings import PermissionSettings
from openharness.permissions.modes import PermissionMode

# Read-only kubectl is allowed; these mutating/dangerous patterns are denied.
KUBECTL_DENY_PATTERNS: list[str] = [
    "kubectl apply*",
    "kubectl delete*",
    "kubectl edit*",
    "kubectl scale*",
    "kubectl patch*",
    "kubectl rollout*",
    "kubectl drain*",
    "kubectl cordon*",
    "kubectl uncordon*",
    "kubectl exec*",
    "kubectl create*",
    "kubectl replace*",
    "kubectl cp*",
    "kubectl set*",
    "kubectl label*",
    "kubectl annotate*",
    "rm *",
    "sudo *",
]


class DatasourceConfig(BaseModel):
    """One HTTP datasource MCP server."""

    name: str
    url: str
    # Name of the env var holding the bearer token for this datasource (optional).
    token_env: str | None = None


class DomoConfig(BaseModel):
    """Runtime config for the domo agent."""

    model: str | None = None
    cwd: str = "."
    permission_mode: str = "full_auto"
    datasources: list[DatasourceConfig] = Field(default_factory=list)

    def permission_settings(self) -> PermissionSettings:
        """Read-mostly policy: allow everything except the kubectl/dangerous deny-list."""
        return PermissionSettings(
            mode=PermissionMode(self.permission_mode),
            denied_commands=list(KUBECTL_DENY_PATTERNS),
        )

    @classmethod
    def from_env(cls) -> "DomoConfig":
        """Load config from environment variables."""
        data: dict[str, object] = {}
        if model := os.environ.get("DOMO_MODEL"):
            data["model"] = model
        if cwd := os.environ.get("DOMO_CWD"):
            data["cwd"] = cwd
        if mode := os.environ.get("DOMO_PERMISSION_MODE"):
            data["permission_mode"] = mode
        return cls(**data)
```
(Datasource loading from env is implemented in Task 4's `mcp_runtime`, which reads `DomoConfig.datasources`; for v1 datasources are populated programmatically or extended later — leave `from_env` as above.)

- [ ] **Step 4: Run to verify it passes**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_config.py -v` → PASS. If `PermissionChecker.evaluate` has a different signature, check `src/openharness/permissions/checker.py` and adjust the test calls (keyword args `is_read_only`, `command`).

- [ ] **Step 5: Commit**
```bash
git add domo/__init__.py domo/config.py tests/test_domo/__init__.py tests/test_domo/test_config.py
git commit -m "feat(domo): DomoConfig with read-mostly kubectl permission policy"
```

---

## Task 3: Persona + bundled skills plugin

**Files:**
- Create: `domo/persona.py`
- Create: `domo/plugin/plugin.json`, `domo/plugin/skills/example-product/SKILL.md`
- Test: `tests/test_domo/test_persona_plugin.py`

- [ ] **Step 1: Write the failing test** — `tests/test_domo/test_persona_plugin.py`:
```python
import json
from pathlib import Path

import domo
from domo.persona import PERSONA


def test_persona_nonempty_and_read_only_guidance():
    assert isinstance(PERSONA, str) and len(PERSONA) > 50
    assert "read-only" in PERSONA.lower() or "do not" in PERSONA.lower()


def test_plugin_manifest_valid():
    root = Path(domo.__file__).parent / "plugin"
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["name"]
    skill = root / "skills" / "example-product" / "SKILL.md"
    assert skill.exists()
    assert skill.read_text().startswith("---")  # frontmatter
```

- [ ] **Step 2: Run to verify it fails**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_persona_plugin.py -v` → FAIL (ModuleNotFoundError: domo.persona)

- [ ] **Step 3: Implement**

`domo/persona.py`:
```python
"""System prompt for the domo domain assistant."""

PERSONA = """You are domo, a domain assistant for an engineering platform.

Your job is to help users retrieve information about the team's products and
check infrastructure state. You have skills describing each product and MCP
tools for querying datasources, plus shell access to read-only `kubectl`.

Operating rules:
- You are READ-ONLY. Retrieve, inspect, summarize. Never mutate infrastructure:
  do not run `kubectl apply/delete/edit/scale/patch/exec` or similar — they are
  blocked, and you should not attempt them.
- Prefer the relevant product skill and datasource MCP before guessing.
- If a request is ambiguous, ask a brief clarifying question INLINE in your
  reply (do not block); then proceed once the user answers.
- Be concise and cite which datasource / command produced each fact.
"""
```

`domo/plugin/plugin.json`:
```json
{
  "name": "domo-skills",
  "version": "0.1.0",
  "description": "Bundled product-knowledge skills for the domo domain assistant.",
  "skills_dir": "skills"
}
```

`domo/plugin/skills/example-product/SKILL.md` (SEED SAMPLE — replace with real product docs):
```markdown
---
name: example-product
description: Use when the user asks about Example Product — what it is, where its data lives, and how to look up its status.
---

# Example Product

This is a seed sample skill. Replace it with real product knowledge.

## What it is
Example Product is a placeholder service used to demonstrate the domo skill format.

## How to retrieve information
- Logs/metrics: query the relevant datasource MCP tool.
- Runtime state: `kubectl get pods -n example-product` (read-only).

## Notes
Document the product's owners, key dashboards, and common queries here.
```

- [ ] **Step 4: Ensure package data is included** — confirm Task 6 adds `domo/plugin/**` to the wheel (force-include); for now the test reads from source tree so it passes locally.

- [ ] **Step 5: Run to verify it passes**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_persona_plugin.py -v` → PASS

- [ ] **Step 6: Commit**
```bash
git add domo/persona.py domo/plugin/ tests/test_domo/test_persona_plugin.py
git commit -m "feat(domo): persona + bundled product-skills plugin (seed sample)"
```

---

## Task 4: Runtime datasource MCP plugin generator

**Files:**
- Create: `domo/mcp_runtime.py`
- Test: `tests/test_domo/test_mcp_runtime.py`

- [ ] **Step 1: Write the failing test** — `tests/test_domo/test_mcp_runtime.py`:
```python
import json

from domo.config import DatasourceConfig, DomoConfig
from domo.mcp_runtime import write_runtime_mcp_plugin


def test_returns_none_when_no_datasources(tmp_path):
    assert write_runtime_mcp_plugin(DomoConfig(), tmp_path) is None


def test_generates_http_mcp_with_token_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMO_DS_METRICS_TOKEN", "secret-tok")
    cfg = DomoConfig(datasources=[
        DatasourceConfig(name="metrics", url="https://m.test/mcp", token_env="DOMO_DS_METRICS_TOKEN")
    ])
    root = write_runtime_mcp_plugin(cfg, tmp_path)
    assert root is not None
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["name"]
    mcp = json.loads((root / ".mcp.json").read_text())
    server = mcp["mcpServers"]["metrics"]
    assert server["type"] == "http"
    assert server["url"] == "https://m.test/mcp"
    assert server["headers"]["Authorization"] == "Bearer secret-tok"


def test_skips_datasource_when_token_env_missing(tmp_path):
    cfg = DomoConfig(datasources=[
        DatasourceConfig(name="metrics", url="https://m.test/mcp", token_env="DOMO_DS_METRICS_TOKEN")
    ])
    root = write_runtime_mcp_plugin(cfg, tmp_path)
    mcp = json.loads((root / ".mcp.json").read_text())
    assert "metrics" not in mcp["mcpServers"]  # skipped: no token in env
```

- [ ] **Step 2: Run to verify it fails**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_mcp_runtime.py -v` → FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement** — `domo/mcp_runtime.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_mcp_runtime.py -v` → PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add domo/mcp_runtime.py tests/test_domo/test_mcp_runtime.py
git commit -m "feat(domo): generate runtime datasource MCP plugin from env"
```

---

## Task 5: Agent factory (`make_build_engine`)

**Files:**
- Create: `domo/agent.py`
- Create: `tests/test_domo/conftest.py` (reuse the A2A fake client)
- Test: `tests/test_domo/test_agent.py`

- [ ] **Step 1: Create the fake-client fixture** — `tests/test_domo/conftest.py`:
```python
"""Reuse the A2A fake streaming client for domo tests."""

import pytest

from tests.test_a2a.conftest import FakeStreamingClient


@pytest.fixture
def fake_client_factory():
    def make(turns):
        return FakeStreamingClient(turns)
    return make
```

- [ ] **Step 2: Write the failing test** — `tests/test_domo/test_agent.py`:
```python
import pytest

from domo.agent import make_build_engine
from domo.config import DomoConfig
from domo.persona import PERSONA


@pytest.mark.asyncio
async def test_build_engine_wires_persona_session_and_permissions(tmp_path, fake_client_factory):
    config = DomoConfig(cwd=str(tmp_path))
    build_engine = make_build_engine(config, api_client=fake_client_factory([["hi"]]))

    engine = await build_engine("ctx-42")

    # persona applied
    assert engine.system_prompt == PERSONA
    # per-conversation memory keyed by contextId
    assert engine.tool_metadata["session_id"] == "ctx-42"
    # domo read-mostly permission policy applied (kubectl delete blocked)
    decision = engine._permission_checker.evaluate(  # noqa: SLF001 - test introspection
        "bash", is_read_only=False, command="kubectl delete pod x"
    )
    assert not decision.allowed
```

- [ ] **Step 3: Run to verify it fails**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_agent.py -v` → FAIL (ModuleNotFoundError: domo.agent)

- [ ] **Step 4: Implement** — `domo/agent.py`:
```python
"""Build a per-conversation QueryEngine for the domo agent."""

from __future__ import annotations

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
        engine = bundle.engine
        # Per-conversation memory: session memory is keyed by session_id.
        engine.tool_metadata["session_id"] = context_id
        # Read-mostly policy (kubectl mutations denied), applied post-build.
        engine.set_permission_checker(PermissionChecker(config.permission_settings()))
        return engine

    return build_engine
```

- [ ] **Step 5: Run to verify it passes**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_agent.py -v` → PASS. (If `engine.system_prompt` is not a property, read `query_engine.py` — it is exposed as a `@property`. If `_permission_checker` access is awkward, the integration test in Task 7 also covers behavior.)

- [ ] **Step 6: Commit**
```bash
git add domo/agent.py tests/test_domo/conftest.py tests/test_domo/test_agent.py
git commit -m "feat(domo): agent factory wiring persona, skills, MCP, per-conversation memory, permissions"
```

---

## Task 6: CLI + packaging

**Files:**
- Create: `domo/cli.py`
- Modify: `pyproject.toml`
- Test: manual (`--help`, import)

- [ ] **Step 1: Implement** — `domo/cli.py`:
```python
"""domo CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(name="domo", help="Domain-assistant agent over A2A")


@app.command("serve")
def serve(
    host: Optional[str] = typer.Option(None, "--host", help="Bind host"),
    port: Optional[int] = typer.Option(None, "--port", help="Bind port"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Agent working directory"),
    model: Optional[str] = typer.Option(None, "--model", help="Model override"),
    public_url: Optional[str] = typer.Option(None, "--public-url", help="Advertised URL"),
) -> None:
    """Run the domo A2A server."""
    from openharness.a2a import A2AServerSettings, run_a2a_server

    from domo.agent import make_build_engine
    from domo.config import DomoConfig

    config = DomoConfig.from_env()
    if cwd:
        config = config.model_copy(update={"cwd": cwd})
    if model:
        config = config.model_copy(update={"model": model})

    a2a_settings = A2AServerSettings.from_env().model_copy(
        update={
            **({"host": host} if host is not None else {}),
            **({"port": port} if port is not None else {}),
            **({"public_url_override": public_url} if public_url else {}),
            "agent_name": "domo",
            "agent_description": "Domain assistant: product info, datasources, infra status.",
        }
    )
    run_a2a_server(
        a2a_settings=a2a_settings,
        cwd=config.cwd or str(Path.cwd()),
        build_engine=make_build_engine(config),
    )


@app.command("doctor")
def doctor() -> None:
    """Print resolved domo + A2A configuration (no server started)."""
    from openharness.a2a import A2AServerSettings

    from domo.config import DomoConfig

    config = DomoConfig.from_env()
    a2a = A2AServerSettings.from_env()
    typer.echo(f"model={config.model} cwd={config.cwd} permission_mode={config.permission_mode}")
    typer.echo(f"datasources={[d.name for d in config.datasources]}")
    typer.echo(f"a2a host={a2a.host} port={a2a.port} auth={'set' if a2a.auth_token else 'open'}")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Update `pyproject.toml`**
- Under `[project.scripts]` add: `domo = "domo.cli:app"`
- Under `[tool.hatch.build.targets.wheel]` `packages` list add `"domo"`.
- Under `[tool.hatch.build.targets.wheel.force-include]` add the skills plugin so it ships:
  `"domo/plugin" = "domo/plugin"`
- Confirm `domo` requires the a2a extra at runtime (document in deploy: install `openharness-ai[a2a]`). No change to core dependencies.

- [ ] **Step 3: Verify**
```bash
uv sync --extra a2a --extra dev
uv run --extra a2a --extra dev domo --help
uv run --extra a2a --extra dev domo doctor
uv run --extra a2a --extra dev python -c "import domo.cli"
```
Expected: `domo --help` lists `serve` + `doctor`; `domo doctor` prints config; import OK.

- [ ] **Step 4: Commit**
```bash
git add domo/cli.py pyproject.toml
git commit -m "feat(domo): domo serve/doctor CLI + packaging"
```

---

## Task 7: Integration test + core regression

**Files:**
- Test: `tests/test_domo/test_server.py`

- [ ] **Step 1: Write the test** — `tests/test_domo/test_server.py`:
```python
import httpx
import pytest

from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH, DEFAULT_RPC_URL

from openharness.a2a.config import A2AServerSettings
from openharness.a2a.server import build_asgi_app
from openharness.a2a.executor import HarnessAgentExecutor  # noqa: F401 (sanity import)
from openharness.services.session_memory import get_session_memory_path

from domo.agent import make_build_engine
from domo.config import DomoConfig


@pytest.mark.asyncio
async def test_card_and_message_with_domo_factory(tmp_path, fake_client_factory):
    config = DomoConfig(cwd=str(tmp_path))
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(agent_name="domo"),
        cwd=str(tmp_path),
        build_engine=make_build_engine(config, api_client=fake_client_factory([["Pong"], ["Pong"]])),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        card = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
        assert card.status_code == 200
        assert card.json()["name"] == "domo"

        rpc = await client.post(DEFAULT_RPC_URL, json={
            "jsonrpc": "2.0", "id": 1, "method": "message/send",
            "params": {"message": {
                "messageId": "m1", "role": "user",
                "parts": [{"text": "ping"}],
                "contextId": "conv-1",
            }},
        })
        assert rpc.status_code == 200
        body = rpc.json()
        assert "error" not in body, body
```
NOTE: the exact JSON-RPC `params.message` shape for a2a-sdk 1.1.0 must match what the SDK expects (proto JSON). If the hand-written body is rejected, use the SDK's client to build the request, OR assert only that the call is routed (status 200 and a JSON-RPC envelope) and verify task completion via a follow-up `tasks/get`. Confirm the working shape against `docs/superpowers/notes/a2a-sdk-api.md` / the SDK during implementation; do not leave it guessed.

- [ ] **Step 2: Run it**

`uv run --extra a2a --extra dev pytest tests/test_domo/test_server.py -v`
Expected: PASS. Adjust the request body to the SDK's accepted shape if needed (see note). If session-memory assertion is added, use `get_session_memory_path(str(tmp_path), "conv-1")` and assert it exists after the call.

- [ ] **Step 3: Core regression**

`uv run --extra a2a --extra dev pytest tests/test_a2a tests/test_domo -q` → all pass.

- [ ] **Step 4: Commit**
```bash
git add tests/test_domo/test_server.py
git commit -m "test(domo): integration — card + message via domo factory; core regression"
```

---

## Task 8: Dockerfile + deploy doc + manual acceptance

**Files:**
- Create: `Dockerfile.domo`, `docs/domo-deploy.md`

- [ ] **Step 1: Write `Dockerfile.domo`**
```dockerfile
FROM python:3.12-slim

# kubectl for read-only infra checks
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -L "https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get purge -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[a2a]"

ENV OPENHARNESS_CONFIG_DIR=/data/openharness
ENV DOMO_CWD=/work
RUN mkdir -p /work

# Secrets injected at runtime (NOT baked): OPENHARNESS_OPENAI_API_KEY, OPENHARNESS_BASE_URL,
# OPENHARNESS_MODEL, OPENHARNESS_A2A_AUTH_TOKEN, DOMO_DS_*_TOKEN. Mount kubeconfig + a /data volume.
ENTRYPOINT ["domo", "serve", "--host", "0.0.0.0", "--port", "9100"]
```

- [ ] **Step 2: Write `docs/domo-deploy.md`** — document: required env vars (provider key/base_url/model, A2A token, `DOMO_DS_*` datasource tokens), mounting kubeconfig (`-v ~/.kube:/root/.kube:ro`), the `/data` volume for session memory, and how to register datasources (extend `DomoConfig.datasources`). Include a `docker run` example.

- [ ] **Step 3: Verify image builds (optional if Docker available)**

`docker build -f Dockerfile.domo -t domo:dev .` → succeeds. (Skip if Docker unavailable; note it.)

- [ ] **Step 4: Manual acceptance** (success criteria, spec §9) — with a real provider + kubeconfig, run `domo serve` and use your A2A CLI client:
  - [ ] Agent Card `name == "domo"`
  - [ ] Ask about a product → skill used
  - [ ] Request data → datasource MCP (http) used
  - [ ] `kubectl get pods` runs; `kubectl delete ...` blocked
  - [ ] Two contextIds keep separate conversation memory
  - [ ] With `OPENHARNESS_A2A_AUTH_TOKEN`: wrong/missing token → 401

- [ ] **Step 5: Commit**
```bash
git add Dockerfile.domo docs/domo-deploy.md
git commit -m "feat(domo): Dockerfile (with kubectl) + deploy doc"
```

---

## Self-review (completed by author)

- **Spec coverage:** §3.1 core inject → Task 1. §3.2 layout → Tasks 2–6. §4 factory/memory → Task 5 (persona + session_id + plugin roots). §5 skills → Task 3; datasource MCP → Task 4; kubectl deny-list → Task 2 (`permission_settings`) applied in Task 5. §6 server/auth/deploy → Tasks 6, 8. §7 testing → per-task + Task 7 + Task 8 manual. §8 risks: risk 2 (session_id post-build) → Task 5; risk 3 (env secrets) → Task 4; risk 1 (input-required deferred) → `ask_user_prompt=None` in Task 5. ✅
- **Placeholder scan:** the seed `SKILL.md` is explicitly labeled a sample to replace (a deliberate starter, not a hidden TODO). The Task 7 JSON-RPC body + Task 8 manual steps carry explicit "confirm shape / requires your client" notes rather than vague placeholders. No "TBD"/"add error handling" hand-waves.
- **Type consistency:** `DomoConfig` (model/cwd/permission_mode/datasources/`permission_settings()`), `DatasourceConfig(name,url,token_env)`, `write_runtime_mcp_plugin(config, dest) -> Path|None`, `make_build_engine(config, api_client=None) -> async build_engine(context_id)`, `PERSONA`, `SessionManager(..., build_engine=...)`, `build_asgi_app(..., build_engine=...)` are used consistently across tasks. ✅
- **Known follow-up:** input-required (core Task 11 of the A2A plan) is intentionally out of scope; domo adopts it later.
