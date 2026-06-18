# LangGraph Harness (lgharness) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small, working standalone CLI agent harness whose engine is a LangGraph `StateGraph` (llm ↔ tools loop) with `interrupt()`-based permission, 3 plain `@tool` tools, and an OpenAI-compatible provider.

**Architecture:** A `StateGraph(MessagesState)` with an `llm` node (calls the bound chat model) and a custom `tools` node (permission-checks each tool call, pauses via `interrupt()` when confirmation is needed, then executes). Compiled with `InMemorySaver` so `interrupt()` works without on-disk persistence. A `QueryEngine` wraps the graph and a `thread_id`, translating LangGraph stream chunks into clean `StreamEvent`s consumed by a `rich`-based REPL.

**Tech Stack:** Python 3.10+, LangGraph, langchain-openai, langchain-core, pydantic, rich, pytest + pytest-asyncio.

## Global Constraints

- Python `>=3.10` (matches repo `requires-python`).
- New deps: `langgraph>=0.2`, `langchain-openai>=0.2`. `langchain-core` comes transitively.
- Provider is **OpenAI-compatible only** (`ChatOpenAI` with `base_url`). No Anthropic/Ollama-native code.
- All code lives under `src/lgharness/`. Do **not** touch `src/openharness/`.
- Package layout mirrors OpenHarness (`engine/`, `tools/`, `permissions/`, `prompts/`, `config/`, `ui/`).
- Tests **never hit the network** — the chat model is faked. Tests run via `pytest`.
- v1 tools: `read_file`, `write_file`, `bash`. v1 permission modes: `default`, `plan`, `full_auto`.
- `read_file` is the only read-only tool (`READ_ONLY_TOOLS = {"read_file"}`).
- Run tests from the worktree root with `python -m pytest`.

---

### Task 1: Foundation — package skeleton, permission modes, settings

**Files:**
- Modify: `pyproject.toml` (add deps extra + script + wheel package)
- Create: `src/lgharness/__init__.py`
- Create: `src/lgharness/permissions/__init__.py`
- Create: `src/lgharness/permissions/modes.py`
- Create: `src/lgharness/config/__init__.py`
- Create: `src/lgharness/config/settings.py`
- Create: `src/lgharness/engine/__init__.py` (empty for now)
- Create: `src/lgharness/tools/__init__.py` (empty for now)
- Create: `src/lgharness/prompts/__init__.py` (empty for now)
- Create: `src/lgharness/ui/__init__.py` (empty for now)
- Create: `tests/lgharness/__init__.py` (empty — mirrors existing `tests/__init__.py` so the suite imports cleanly)
- Test: `tests/lgharness/test_settings.py`

**Interfaces:**
- Produces: `lgharness.permissions.modes.PermissionMode` (str Enum: `DEFAULT="default"`, `PLAN="plan"`, `FULL_AUTO="full_auto"`).
- Produces: `lgharness.config.settings.Settings` (pydantic `BaseModel`) with fields `base_url: str`, `api_key: str`, `model: str = "gpt-4o-mini"`, `permission_mode: PermissionMode = PermissionMode.DEFAULT`, `max_turns: int = 25`; classmethod `Settings.from_env(**overrides) -> Settings`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_settings.py
import os
import pytest
from lgharness.config.settings import Settings
from lgharness.permissions.modes import PermissionMode


def test_defaults():
    s = Settings(base_url="http://x/v1", api_key="k")
    assert s.model == "gpt-4o-mini"
    assert s.permission_mode == PermissionMode.DEFAULT
    assert s.max_turns == 25


def test_from_env_reads_and_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "envkey")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env/v1")
    s = Settings.from_env(model="gpt-test")
    assert s.api_key == "envkey"
    assert s.base_url == "http://env/v1"
    assert s.model == "gpt-test"


def test_permission_mode_coerces_from_string():
    s = Settings(base_url="b", api_key="k", permission_mode="full_auto")
    assert s.permission_mode is PermissionMode.FULL_AUTO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lgharness'`

- [ ] **Step 3: Add dependencies and packaging to pyproject.toml**

In `pyproject.toml`, under `[project.optional-dependencies]` add:

```toml
lgharness = [
    "langgraph>=0.2",
    "langchain-openai>=0.2",
]
```

Under `[project.scripts]` add:

```toml
lgharness = "lgharness.cli:app"
```

Under `[tool.hatch.build.targets.wheel]`, change the packages line to include the new package:

```toml
packages = ["src/openharness", "ohmo", "domo", "src/lgharness"]
```

Then install the deps into the active environment:

Run: `python -m pip install 'langgraph>=0.2' 'langchain-openai>=0.2'`
Expected: installs successfully.

- [ ] **Step 4: Create the package skeleton**

```python
# src/lgharness/__init__.py
"""LangGraph-based agent harness (lgharness)."""
```

Create empty `__init__.py` files (each containing only a one-line docstring) at:
`src/lgharness/engine/__init__.py`, `src/lgharness/tools/__init__.py`,
`src/lgharness/prompts/__init__.py`, `src/lgharness/ui/__init__.py`,
`src/lgharness/permissions/__init__.py`, `src/lgharness/config/__init__.py`.

Example:

```python
# src/lgharness/permissions/__init__.py
"""Permission subsystem."""
```

Also create an empty test package marker:

```python
# tests/lgharness/__init__.py
```

(Tests rely on `asyncio_mode = "auto"` already set in `pyproject.toml`, so async tests run without extra config.)

- [ ] **Step 5: Implement permission modes**

```python
# src/lgharness/permissions/modes.py
"""Permission mode definitions."""

from __future__ import annotations

from enum import Enum


class PermissionMode(str, Enum):
    """Supported permission modes."""

    DEFAULT = "default"
    PLAN = "plan"
    FULL_AUTO = "full_auto"
```

- [ ] **Step 6: Implement settings**

```python
# src/lgharness/config/settings.py
"""Harness configuration."""

from __future__ import annotations

import os

from pydantic import BaseModel

from lgharness.permissions.modes import PermissionMode


class Settings(BaseModel):
    """Runtime configuration for a harness session."""

    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    max_turns: int = 25

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build settings from OPENAI_* env vars, with explicit overrides."""
        values: dict[str, object] = {
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_settings.py -v`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/lgharness tests/lgharness/test_settings.py
git commit -m "feat(lgharness): package skeleton, permission modes, settings"
```

---

### Task 2: Permission checker

**Files:**
- Create: `src/lgharness/permissions/checker.py`
- Test: `tests/lgharness/test_permissions.py`

**Interfaces:**
- Consumes: `PermissionMode` from Task 1.
- Produces: `lgharness.permissions.checker.READ_ONLY_TOOLS: frozenset[str]` (`= frozenset({"read_file"})`).
- Produces: `lgharness.permissions.checker.PermissionDecision` (frozen dataclass: `allowed: bool`, `requires_confirmation: bool = False`, `reason: str = ""`).
- Produces: `lgharness.permissions.checker.PermissionChecker(mode: PermissionMode)` with `evaluate(tool_name: str) -> PermissionDecision`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_permissions.py
from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode


def test_read_only_always_allowed():
    for mode in PermissionMode:
        d = PermissionChecker(mode).evaluate("read_file")
        assert d.allowed is True
        assert d.requires_confirmation is False


def test_full_auto_allows_mutating():
    d = PermissionChecker(PermissionMode.FULL_AUTO).evaluate("write_file")
    assert d.allowed is True
    assert d.requires_confirmation is False


def test_default_mode_confirms_mutating():
    d = PermissionChecker(PermissionMode.DEFAULT).evaluate("bash")
    assert d.allowed is False
    assert d.requires_confirmation is True


def test_plan_mode_blocks_mutating_without_asking():
    d = PermissionChecker(PermissionMode.PLAN).evaluate("write_file")
    assert d.allowed is False
    assert d.requires_confirmation is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_permissions.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` for `checker`.

- [ ] **Step 3: Implement the checker**

```python
# src/lgharness/permissions/checker.py
"""Permission checking for tool execution."""

from __future__ import annotations

from dataclasses import dataclass

from lgharness.permissions.modes import PermissionMode

# Tools that never mutate state and are always safe to run.
READ_ONLY_TOOLS: frozenset[str] = frozenset({"read_file"})


@dataclass(frozen=True)
class PermissionDecision:
    """Result of checking whether a tool invocation may run."""

    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


class PermissionChecker:
    """Evaluate a tool call against the active permission mode."""

    def __init__(self, mode: PermissionMode) -> None:
        self._mode = mode

    def evaluate(self, tool_name: str) -> PermissionDecision:
        """Return whether the named tool may run, or needs confirmation."""
        if self._mode == PermissionMode.FULL_AUTO:
            return PermissionDecision(allowed=True, reason="full_auto allows all tools")

        if tool_name in READ_ONLY_TOOLS:
            return PermissionDecision(allowed=True, reason="read-only tool")

        if self._mode == PermissionMode.PLAN:
            return PermissionDecision(
                allowed=False,
                requires_confirmation=False,
                reason="plan mode blocks mutating tools",
            )

        # DEFAULT mode: mutating tools require confirmation.
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="mutating tool requires user confirmation in default mode",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_permissions.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/lgharness/permissions/checker.py tests/lgharness/test_permissions.py
git commit -m "feat(lgharness): permission checker with mode-aware decisions"
```

---

### Task 3: Tools (read_file, write_file, bash)

**Files:**
- Create: `src/lgharness/tools/fs.py`
- Create: `src/lgharness/tools/shell.py`
- Modify: `src/lgharness/tools/__init__.py`
- Test: `tests/lgharness/test_tools.py`

**Interfaces:**
- Produces: `lgharness.tools.fs.read_file`, `lgharness.tools.fs.write_file` (LangChain `@tool` async, names `"read_file"` / `"write_file"`).
- Produces: `lgharness.tools.shell.bash` (LangChain `@tool` async, name `"bash"`).
- Produces: `lgharness.tools.DEFAULT_TOOLS: list` and `lgharness.tools.TOOLS_BY_NAME: dict[str, ...]`.
- Note: each tool is invoked in the graph via `await tool.ainvoke(args_dict)` and returns a `str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_tools.py
import pytest

from lgharness.tools import DEFAULT_TOOLS, TOOLS_BY_NAME
from lgharness.tools.fs import read_file, write_file
from lgharness.tools.shell import bash


def test_registry_contents():
    assert {t.name for t in DEFAULT_TOOLS} == {"read_file", "write_file", "bash"}
    assert set(TOOLS_BY_NAME) == {"read_file", "write_file", "bash"}


@pytest.mark.asyncio
async def test_write_then_read(tmp_path):
    target = tmp_path / "note.txt"
    out = await write_file.ainvoke({"path": str(target), "content": "hello"})
    assert "hello" not in out  # returns a status, not the content
    assert target.read_text() == "hello"

    content = await read_file.ainvoke({"path": str(target)})
    assert "hello" in content


@pytest.mark.asyncio
async def test_read_missing_file(tmp_path):
    out = await read_file.ainvoke({"path": str(tmp_path / "nope.txt")})
    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_bash_echo():
    out = await bash.ainvoke({"command": "echo hi"})
    assert "hi" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_tools.py -v`
Expected: FAIL with `ImportError` (no `fs`/`shell` modules).

- [ ] **Step 3: Implement filesystem tools**

```python
# src/lgharness/tools/fs.py
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
```

- [ ] **Step 4: Implement the shell tool**

```python
# src/lgharness/tools/shell.py
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
```

- [ ] **Step 5: Implement the tool registry**

```python
# src/lgharness/tools/__init__.py
"""Tool registry for the harness."""

from __future__ import annotations

from lgharness.tools.fs import read_file, write_file
from lgharness.tools.shell import bash

DEFAULT_TOOLS = [read_file, write_file, bash]
TOOLS_BY_NAME = {t.name: t for t in DEFAULT_TOOLS}

__all__ = ["DEFAULT_TOOLS", "TOOLS_BY_NAME", "read_file", "write_file", "bash"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_tools.py -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/lgharness/tools tests/lgharness/test_tools.py
git commit -m "feat(lgharness): read_file, write_file, bash tools + registry"
```

---

### Task 4: Stream events + system prompt + model factory

**Files:**
- Create: `src/lgharness/engine/stream_events.py`
- Create: `src/lgharness/prompts/system_prompt.py`
- Create: `src/lgharness/model.py`
- Test: `tests/lgharness/test_stream_events.py`

**Interfaces:**
- Produces stream event dataclasses (frozen) in `lgharness.engine.stream_events`:
  - `AssistantMessage(text: str)`
  - `ToolExecutionStarted(tool_name: str, tool_input: dict)`
  - `ToolExecutionCompleted(tool_name: str, output: str, is_error: bool = False)`
  - `PermissionRequest(requests: list[dict])` — each dict has keys `id`, `name`, `args`.
  - `ErrorEvent(message: str)`
  - `StreamEvent` union type alias.
- Produces: `lgharness.prompts.system_prompt.build_system_prompt(cwd: str) -> str`.
- Produces: `lgharness.model.build_model(settings: Settings)` returning a tools-bound `ChatOpenAI` runnable.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_stream_events.py
from lgharness.engine.stream_events import (
    AssistantMessage,
    ErrorEvent,
    PermissionRequest,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from lgharness.prompts.system_prompt import build_system_prompt


def test_event_fields():
    assert AssistantMessage(text="hi").text == "hi"
    assert ToolExecutionStarted(tool_name="bash", tool_input={"command": "ls"}).tool_name == "bash"
    c = ToolExecutionCompleted(tool_name="bash", output="ok")
    assert c.is_error is False
    assert PermissionRequest(requests=[{"id": "1", "name": "bash", "args": {}}]).requests[0]["name"] == "bash"
    assert ErrorEvent(message="boom").message == "boom"


def test_system_prompt_mentions_tools_and_cwd():
    p = build_system_prompt("/tmp/work")
    assert "/tmp/work" in p
    for name in ("read_file", "write_file", "bash"):
        assert name in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_stream_events.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement stream events**

```python
# src/lgharness/engine/stream_events.py
"""Events yielded by the query engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AssistantMessage:
    """A completed assistant text reply."""

    text: str


@dataclass(frozen=True)
class ToolExecutionStarted:
    """The engine is about to execute a tool."""

    tool_name: str
    tool_input: dict


@dataclass(frozen=True)
class ToolExecutionCompleted:
    """A tool has finished executing."""

    tool_name: str
    output: str
    is_error: bool = False


@dataclass(frozen=True)
class PermissionRequest:
    """The graph paused to request permission for one or more tool calls."""

    requests: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ErrorEvent:
    """An error surfaced to the user."""

    message: str


StreamEvent = (
    AssistantMessage
    | ToolExecutionStarted
    | ToolExecutionCompleted
    | PermissionRequest
    | ErrorEvent
)
```

- [ ] **Step 4: Implement the system prompt**

```python
# src/lgharness/prompts/system_prompt.py
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
```

- [ ] **Step 5: Implement the model factory**

```python
# src/lgharness/model.py
"""Chat model factory (OpenAI-compatible)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from lgharness.config.settings import Settings
from lgharness.tools import DEFAULT_TOOLS


def build_model(settings: Settings):
    """Return a tools-bound OpenAI-compatible chat model."""
    model = ChatOpenAI(
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        temperature=0,
    )
    return model.bind_tools(DEFAULT_TOOLS)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_stream_events.py -v`
Expected: 2 passed.

(Note: `model.py` is exercised indirectly; it is not unit-tested because constructing `ChatOpenAI` and binding tools requires no network and any failure would surface in Step 6's import chain via `tests` that import `lgharness.tools`. A dedicated test is omitted per YAGNI — it would only assert that LangChain constructs an object.)

- [ ] **Step 7: Commit**

```bash
git add src/lgharness/engine/stream_events.py src/lgharness/prompts/system_prompt.py src/lgharness/model.py tests/lgharness/test_stream_events.py
git commit -m "feat(lgharness): stream events, system prompt, model factory"
```

---

### Task 5: Graph nodes + builder (agent loop with permission interrupt)

**Files:**
- Create: `src/lgharness/engine/nodes.py`
- Create: `src/lgharness/engine/graph.py`
- Test: `tests/lgharness/test_graph.py`

**Interfaces:**
- Consumes: `PermissionChecker` (Task 2), `TOOLS_BY_NAME` (Task 3), `PermissionMode` (Task 1).
- Produces: `lgharness.engine.nodes.make_llm_node(model)` → async node `(state) -> dict`.
- Produces: `lgharness.engine.nodes.make_tools_node(checker)` → async node `(state) -> dict`. This node permission-checks each tool call; collects calls needing confirmation; calls `interrupt({"requests": [...]})` **once**; the resume value is a `dict[str, bool]` mapping `tool_call_id -> approved`. Allowed/approved calls run via `await tool.ainvoke(args)`; denied calls produce an error `ToolMessage`.
- Produces: `lgharness.engine.nodes.route_after_llm(state) -> str` returning `"tools"` or `END`.
- Produces: `lgharness.engine.graph.build_graph(model, checker)` → compiled graph (with `InMemorySaver`).

**Behavioral contract for `make_tools_node`:**
- Reads the last message's `.tool_calls` (list of dicts: `name`, `args`, `id`).
- For each call: `decision = checker.evaluate(name)`. `allowed` → run. `requires_confirmation` → add to `pending`. else (denied) → error ToolMessage "blocked by permission policy".
- If `pending` non-empty: `answers = interrupt({"requests": [{"id","name","args"} ...]})`; treat `answers` as `dict[str,bool]`; for each pending call, run if `answers.get(id)` is truthy, else error ToolMessage "denied by user".
- Returns `{"messages": [ToolMessage(...), ...]}` in the original tool_call order.

- [ ] **Step 1: Write the failing tests**

```python
# tests/lgharness/test_graph.py
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from lgharness.engine.graph import build_graph
from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode


class FakeModel:
    """A scripted stand-in for a tools-bound chat model.

    Returns queued AIMessages in order on each ``ainvoke`` call.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    async def ainvoke(self, messages, **kwargs):
        msg = self._responses[self._i]
        self._i += 1
        return msg


def _tool_call(name, args, id):
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


@pytest.mark.asyncio
async def test_loop_runs_read_only_tool_then_finishes(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("DATA")
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tool_call("read_file", {"path": str(target)}, "c1")]),
        AIMessage(content="The file says DATA."),
    ])
    graph = build_graph(model, PermissionChecker(PermissionMode.DEFAULT))
    config = {"configurable": {"thread_id": "t1"}}
    result = await graph.ainvoke({"messages": [HumanMessage("read it")]}, config)
    texts = [m.content for m in result["messages"] if isinstance(m, AIMessage)]
    assert "The file says DATA." in texts
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("DATA" in m.content for m in tool_msgs)


@pytest.mark.asyncio
async def test_mutating_tool_interrupts_then_approves(tmp_path):
    target = tmp_path / "out.txt"
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tool_call("write_file", {"path": str(target), "content": "X"}, "c1")]),
        AIMessage(content="Done."),
    ])
    graph = build_graph(model, PermissionChecker(PermissionMode.DEFAULT))
    config = {"configurable": {"thread_id": "t2"}}
    # First stream pauses on interrupt; file must NOT exist yet.
    result = await graph.ainvoke({"messages": [HumanMessage("write X")]}, config)
    assert "__interrupt__" in result
    assert not target.exists()
    # Approve -> resume.
    final = await graph.ainvoke(Command(resume={"c1": True}), config)
    assert target.read_text() == "X"
    assert any(isinstance(m, AIMessage) and m.content == "Done." for m in final["messages"])


@pytest.mark.asyncio
async def test_mutating_tool_interrupt_denied(tmp_path):
    target = tmp_path / "out.txt"
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tool_call("write_file", {"path": str(target), "content": "X"}, "c1")]),
        AIMessage(content="Understood, skipped."),
    ])
    graph = build_graph(model, PermissionChecker(PermissionMode.DEFAULT))
    config = {"configurable": {"thread_id": "t3"}}
    await graph.ainvoke({"messages": [HumanMessage("write X")]}, config)
    final = await graph.ainvoke(Command(resume={"c1": False}), config)
    assert not target.exists()
    tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
    assert any("denied" in m.content.lower() for m in tool_msgs)


@pytest.mark.asyncio
async def test_plan_mode_blocks_without_interrupt(tmp_path):
    target = tmp_path / "out.txt"
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tool_call("write_file", {"path": str(target), "content": "X"}, "c1")]),
        AIMessage(content="Blocked."),
    ])
    graph = build_graph(model, PermissionChecker(PermissionMode.PLAN))
    config = {"configurable": {"thread_id": "t4"}}
    result = await graph.ainvoke({"messages": [HumanMessage("write X")]}, config)
    assert "__interrupt__" not in result
    assert not target.exists()
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("policy" in m.content.lower() for m in tool_msgs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/lgharness/test_graph.py -v`
Expected: FAIL with `ImportError` for `lgharness.engine.graph`.

- [ ] **Step 3: Implement the nodes**

```python
# src/lgharness/engine/nodes.py
"""LangGraph nodes for the agent loop."""

from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt

from lgharness.permissions.checker import PermissionChecker
from lgharness.tools import TOOLS_BY_NAME


def make_llm_node(model):
    """Build the node that calls the chat model."""

    async def llm_node(state: dict) -> dict:
        response = await model.ainvoke(state["messages"])
        return {"messages": [response]}

    return llm_node


def route_after_llm(state: dict) -> str:
    """Route to the tools node when the last message requested tools."""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def make_tools_node(checker: PermissionChecker):
    """Build the node that permission-checks and executes tool calls."""

    async def tools_node(state: dict) -> dict:
        last = state["messages"][-1]
        calls = last.tool_calls

        approved: dict[str, bool] = {}
        blocked: dict[str, str] = {}
        pending: list[dict] = []

        for call in calls:
            decision = checker.evaluate(call["name"])
            if decision.allowed:
                approved[call["id"]] = True
            elif decision.requires_confirmation:
                pending.append(call)
            else:
                blocked[call["id"]] = decision.reason or "blocked by permission policy"

        if pending:
            answers = interrupt(
                {
                    "requests": [
                        {"id": c["id"], "name": c["name"], "args": c["args"]}
                        for c in pending
                    ]
                }
            )
            answers = answers or {}
            for call in pending:
                approved[call["id"]] = bool(answers.get(call["id"]))

        messages: list[ToolMessage] = []
        for call in calls:
            cid = call["id"]
            if cid in blocked:
                messages.append(
                    ToolMessage(
                        content=f"Blocked by permission policy: {blocked[cid]}",
                        tool_call_id=cid,
                        status="error",
                    )
                )
                continue
            if not approved.get(cid):
                messages.append(
                    ToolMessage(
                        content="Tool call denied by user.",
                        tool_call_id=cid,
                        status="error",
                    )
                )
                continue
            tool = TOOLS_BY_NAME.get(call["name"])
            if tool is None:
                messages.append(
                    ToolMessage(
                        content=f"Unknown tool: {call['name']}",
                        tool_call_id=cid,
                        status="error",
                    )
                )
                continue
            try:
                output = await tool.ainvoke(call["args"])
            except Exception as exc:  # surface tool errors back to the model
                messages.append(
                    ToolMessage(
                        content=f"Tool {call['name']} failed: {type(exc).__name__}: {exc}",
                        tool_call_id=cid,
                        status="error",
                    )
                )
                continue
            messages.append(ToolMessage(content=str(output), tool_call_id=cid))

        return {"messages": messages}

    return tools_node
```

- [ ] **Step 4: Implement the graph builder**

```python
# src/lgharness/engine/graph.py
"""Agent-loop graph construction."""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from lgharness.engine.nodes import make_llm_node, make_tools_node, route_after_llm
from lgharness.permissions.checker import PermissionChecker


def build_graph(model, checker: PermissionChecker):
    """Build and compile the llm <-> tools agent loop graph."""
    builder = StateGraph(MessagesState)
    builder.add_node("llm", make_llm_node(model))
    builder.add_node("tools", make_tools_node(checker))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", route_after_llm, {"tools": "tools", "__end__": "__end__"})
    builder.add_edge("tools", "llm")
    return builder.compile(checkpointer=InMemorySaver())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_graph.py -v`
Expected: 4 passed.

If `add_conditional_edges` rejects the path map, replace the mapping with the plain form `builder.add_conditional_edges("llm", route_after_llm)` (since `route_after_llm` already returns either `"tools"` or the `END` sentinel).

- [ ] **Step 6: Commit**

```bash
git add src/lgharness/engine/nodes.py src/lgharness/engine/graph.py tests/lgharness/test_graph.py
git commit -m "feat(lgharness): agent-loop graph with permission interrupt"
```

---

### Task 6: QueryEngine (stream translation)

**Files:**
- Create: `src/lgharness/engine/query_engine.py`
- Test: `tests/lgharness/test_query_engine.py`

**Interfaces:**
- Consumes: `build_graph` (Task 5), stream events (Task 4), `PermissionChecker` (Task 2), `build_system_prompt` (Task 4).
- Produces: `lgharness.engine.query_engine.QueryEngine`.
  - `__init__(self, model, checker, *, cwd: str)` — builds the graph, assigns a random `thread_id`, stores a `SystemMessage(build_system_prompt(cwd))` to prepend on the first turn.
  - `async submit_message(self, text: str) -> AsyncIterator[StreamEvent]` — streams the graph from a new `HumanMessage`; yields `ToolExecutionStarted` per tool call, `ToolExecutionCompleted` per `ToolMessage`, `AssistantMessage` for a final assistant text, and `PermissionRequest` when paused.
  - `async resume(self, answers: dict[str, bool]) -> AsyncIterator[StreamEvent]` — resumes with `Command(resume=answers)` and yields the same event types.
  - `property pending: bool` — True if the last stream ended on an interrupt.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_query_engine.py
import pytest
from langchain_core.messages import AIMessage

from lgharness.engine.query_engine import QueryEngine
from lgharness.engine.stream_events import (
    AssistantMessage,
    PermissionRequest,
    ToolExecutionCompleted,
)
from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode


class FakeModel:
    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    async def ainvoke(self, messages, **kwargs):
        msg = self._responses[self._i]
        self._i += 1
        return msg


def _tc(name, args, id):
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


@pytest.mark.asyncio
async def test_plain_assistant_reply(tmp_path):
    model = FakeModel([AIMessage(content="Hello there.")])
    engine = QueryEngine(model, PermissionChecker(PermissionMode.DEFAULT), cwd=str(tmp_path))
    events = [e async for e in engine.submit_message("hi")]
    assert any(isinstance(e, AssistantMessage) and e.text == "Hello there." for e in events)
    assert engine.pending is False


@pytest.mark.asyncio
async def test_read_only_tool_completes(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("DATA")
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tc("read_file", {"path": str(f)}, "c1")]),
        AIMessage(content="done"),
    ])
    engine = QueryEngine(model, PermissionChecker(PermissionMode.DEFAULT), cwd=str(tmp_path))
    events = [e async for e in engine.submit_message("read a.txt")]
    assert any(isinstance(e, ToolExecutionCompleted) and "DATA" in e.output for e in events)


@pytest.mark.asyncio
async def test_permission_request_then_resume(tmp_path):
    target = tmp_path / "w.txt"
    model = FakeModel([
        AIMessage(content="", tool_calls=[_tc("write_file", {"path": str(target), "content": "Z"}, "c1")]),
        AIMessage(content="written"),
    ])
    engine = QueryEngine(model, PermissionChecker(PermissionMode.DEFAULT), cwd=str(tmp_path))
    events = [e async for e in engine.submit_message("write Z")]
    reqs = [e for e in events if isinstance(e, PermissionRequest)]
    assert reqs and reqs[0].requests[0]["name"] == "write_file"
    assert engine.pending is True

    resumed = [e async for e in engine.resume({"c1": True})]
    assert target.read_text() == "Z"
    assert any(isinstance(e, AssistantMessage) and e.text == "written" for e in resumed)
    assert engine.pending is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_query_engine.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the QueryEngine**

```python
# src/lgharness/engine/query_engine.py
"""High-level engine wrapping the LangGraph agent loop."""

from __future__ import annotations

from typing import AsyncIterator
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from lgharness.engine.graph import build_graph
from lgharness.engine.stream_events import (
    AssistantMessage,
    ErrorEvent,
    PermissionRequest,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from lgharness.permissions.checker import PermissionChecker
from lgharness.prompts.system_prompt import build_system_prompt


class QueryEngine:
    """Owns the compiled graph + thread id and emits clean stream events."""

    def __init__(self, model, checker: PermissionChecker, *, cwd: str) -> None:
        self._graph = build_graph(model, checker)
        self._thread_id = uuid4().hex
        self._config = {"configurable": {"thread_id": self._thread_id}}
        self._system = SystemMessage(build_system_prompt(cwd))
        self._first_turn = True
        self._pending = False

    @property
    def pending(self) -> bool:
        """True when the last run paused awaiting permission."""
        return self._pending

    async def submit_message(self, text: str) -> AsyncIterator[StreamEvent]:
        """Append a user message and stream the agent loop."""
        initial: list = []
        if self._first_turn:
            initial.append(self._system)
            self._first_turn = False
        initial.append(HumanMessage(text))
        async for event in self._run({"messages": initial}):
            yield event

    async def resume(self, answers: dict[str, bool]) -> AsyncIterator[StreamEvent]:
        """Resume a paused run with per-tool-call approval decisions."""
        async for event in self._run(Command(resume=answers)):
            yield event

    async def _run(self, graph_input) -> AsyncIterator[StreamEvent]:
        self._pending = False
        try:
            async for chunk in self._graph.astream(
                graph_input, self._config, stream_mode="updates"
            ):
                if "__interrupt__" in chunk:
                    interrupts = chunk["__interrupt__"]
                    value = interrupts[0].value if interrupts else {}
                    self._pending = True
                    yield PermissionRequest(requests=list(value.get("requests", [])))
                    return
                for node_name, payload in chunk.items():
                    for event in self._translate(node_name, payload):
                        yield event
        except Exception as exc:
            yield ErrorEvent(message=f"{type(exc).__name__}: {exc}")

    def _translate(self, node_name: str, payload) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        messages = (payload or {}).get("messages", []) if isinstance(payload, dict) else []
        for msg in messages:
            if isinstance(msg, AIMessage):
                if getattr(msg, "tool_calls", None):
                    for call in msg.tool_calls:
                        events.append(
                            ToolExecutionStarted(tool_name=call["name"], tool_input=call["args"])
                        )
                if isinstance(msg.content, str) and msg.content.strip():
                    events.append(AssistantMessage(text=msg.content))
            elif isinstance(msg, ToolMessage):
                events.append(
                    ToolExecutionCompleted(
                        tool_name=getattr(msg, "name", "") or "",
                        output=str(msg.content),
                        is_error=getattr(msg, "status", None) == "error",
                    )
                )
        return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_query_engine.py -v`
Expected: 3 passed.

If `ToolExecutionCompleted.tool_name` comes back empty in the assertion-free path and you later need the name, note that `ToolMessage.name` is populated by LangGraph from the tool call; the test only asserts on `output`, so an empty name is acceptable for v1.

- [ ] **Step 5: Commit**

```bash
git add src/lgharness/engine/query_engine.py tests/lgharness/test_query_engine.py
git commit -m "feat(lgharness): QueryEngine translating graph stream to events"
```

---

### Task 7: REPL + CLI entrypoint

**Files:**
- Create: `src/lgharness/ui/repl.py`
- Create: `src/lgharness/cli.py`
- Create: `src/lgharness/__main__.py`
- Test: `tests/lgharness/test_cli.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `build_model` (Task 4), `PermissionChecker` (Task 2), `QueryEngine` (Task 6), all stream events.
- Produces: `lgharness.cli.build_parser() -> argparse.ArgumentParser`.
- Produces: `lgharness.cli.app(argv: list[str] | None = None) -> int` — parses args, builds `Settings.from_env(...)`, constructs model + engine, runs the REPL via `asyncio.run`.
- Produces: `lgharness.ui.repl.run_repl(engine) -> Awaitable[None]` and `lgharness.ui.repl.render(event, console) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/lgharness/test_cli.py
from lgharness.cli import build_parser
from lgharness.permissions.modes import PermissionMode


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.permission_mode is None
    assert args.model is None


def test_parser_flags():
    args = build_parser().parse_args(
        ["--model", "gpt-x", "--base-url", "http://h/v1", "--permission-mode", "full_auto"]
    )
    assert args.model == "gpt-x"
    assert args.base_url == "http://h/v1"
    assert args.permission_mode == "full_auto"


def test_permission_mode_choices_match_enum():
    parser = build_parser()
    # All enum values must be accepted choices.
    for mode in PermissionMode:
        ns = parser.parse_args(["--permission-mode", mode.value])
        assert ns.permission_mode == mode.value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/lgharness/test_cli.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the REPL**

```python
# src/lgharness/ui/repl.py
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
```

- [ ] **Step 4: Implement the CLI**

```python
# src/lgharness/cli.py
"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio

from lgharness.config.settings import Settings
from lgharness.model import build_model
from lgharness.engine.query_engine import QueryEngine
from lgharness.permissions.checker import PermissionChecker
from lgharness.permissions.modes import PermissionMode
from lgharness.ui.repl import run_repl


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="lgharness", description="LangGraph agent harness")
    parser.add_argument("--model", default=None, help="model id")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible base URL")
    parser.add_argument(
        "--permission-mode",
        default=None,
        choices=[m.value for m in PermissionMode],
        help="permission mode",
    )
    return parser


def app(argv: list[str] | None = None) -> int:
    """Parse args, build the engine, and run the REPL."""
    import os

    args = build_parser().parse_args(argv)
    settings = Settings.from_env(
        model=args.model,
        base_url=args.base_url,
        permission_mode=args.permission_mode,
    )
    if not settings.api_key:
        print("error: set OPENAI_API_KEY (and optionally OPENAI_BASE_URL).")
        return 1
    model = build_model(settings)
    engine = QueryEngine(model, PermissionChecker(settings.permission_mode), cwd=os.getcwd())
    asyncio.run(run_repl(engine))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(app())
```

- [ ] **Step 5: Implement `__main__`**

```python
# src/lgharness/__main__.py
"""python -m lgharness entrypoint."""

from lgharness.cli import app

if __name__ == "__main__":
    raise SystemExit(app())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/lgharness/test_cli.py -v`
Expected: 3 passed.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest tests/lgharness/ -v`
Expected: all tests pass (settings, permissions, tools, stream_events, graph, query_engine, cli).

- [ ] **Step 8: Commit**

```bash
git add src/lgharness/ui/repl.py src/lgharness/cli.py src/lgharness/__main__.py tests/lgharness/test_cli.py
git commit -m "feat(lgharness): REPL and CLI entrypoint"
```

---

### Task 8: Manual smoke test + README

**Files:**
- Create: `src/lgharness/README.md`
- Test: manual (documented below)

**Interfaces:** none (documentation + manual verification only).

- [ ] **Step 1: Write a short README**

```markdown
# lgharness

A small LangGraph-based agent harness CLI.

## Run

    export OPENAI_API_KEY=sk-...
    export OPENAI_BASE_URL=https://your-openai-compatible/v1   # optional
    python -m lgharness --model gpt-4o-mini

## Permission modes

- `default` (ask before write_file / bash)
- `full_auto` (no prompts)
- `plan` (block mutating tools)

    python -m lgharness --permission-mode full_auto
```

- [ ] **Step 2: Manual smoke test (requires a real OpenAI-compatible endpoint)**

Run:

```bash
export OPENAI_API_KEY=...        # your key
export OPENAI_BASE_URL=...       # your endpoint, if not api.openai.com
python -m lgharness
```

Verify, in order:
1. REPL opens with the `lgharness` banner.
2. Prompt: "read the file ./pyproject.toml and tell me the project name" → the
   model calls `read_file`, it runs **without** a permission prompt, and the
   answer mentions the name.
3. Prompt: "create a file /tmp/lg_demo.txt containing hello" → a permission
   prompt appears. Answer `n` → file is NOT created and the model acknowledges
   the denial. Repeat and answer `y` → `cat /tmp/lg_demo.txt` shows `hello`.
4. Restart with `--permission-mode full_auto` and repeat step 3 → no prompt,
   file created directly.
5. Restart with `--permission-mode plan` and repeat step 3 → tool is blocked,
   no prompt, model is told the policy blocked it.
6. `/exit` quits.

- [ ] **Step 3: Commit**

```bash
git add src/lgharness/README.md
git commit -m "docs(lgharness): usage README"
```

---

## Notes for the implementer

- **Why no `ToolNode`:** permission + `interrupt()` must run *between* the model
  requesting a tool and the tool executing, so the tools node is hand-written.
- **Interrupt re-run safety:** `tools_node` calls `interrupt()` **once** for all
  pending calls and executes tools only *after* it resolves. On resume the node
  re-runs from the top, but re-evaluation (permission checks) is pure, so no tool
  runs twice.
- **Checkpointer:** `InMemorySaver` is required for `interrupt()` to work; it
  keeps state in RAM per `thread_id` and is lost on exit (v1 has no on-disk
  persistence by design).
- **Fake model in tests:** any object with `async ainvoke(messages, **kwargs)`
  returning an `AIMessage` works; no network and no `bind_tools` needed because
  `build_graph` receives an already-bound model.
```

