# OpenTelemetry Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit OpenTelemetry spans for the agent loop (one trace per user input: `user_input → turn → {chat, execute_tool}`) so a developer can debug what the agent did, with timings, token usage, and errors.

**Architecture:** A new self-contained `src/openharness/observability/` package owns all OTel concerns behind a thin facade that is a no-op unless OTel is installed *and* an exporter is selected via `OTEL_TRACES_EXPORTER`. The engine (`query.py`, `query_engine.py`) calls the facade at four boundaries. Span parenting uses an explicit `contextvars` parent (linked via `set_span_in_context`) so the tree is correct across the async-generator yields and concurrent `asyncio.gather` tool tasks.

**Tech Stack:** Python 3.10+, `opentelemetry-api`/`-sdk`/`-exporter-otlp` (optional extra), pytest + `opentelemetry`'s `InMemorySpanExporter`.

**Spec:** `docs/superpowers/specs/2026-06-14-otel-observability-design.md`

---

## File Structure

- Create: `src/openharness/observability/__init__.py` — public facade re-exports
- Create: `src/openharness/observability/tracing.py` — provider/exporter setup from env + test hooks
- Create: `src/openharness/observability/spans.py` — span context-managers, attribute setters, content gate
- Modify: `src/openharness/engine/query.py` — turn span, model-call span, tool spans
- Modify: `src/openharness/engine/query_engine.py` — root `user_input` span
- Modify: `src/openharness/cli.py` — call `init_tracing()` at startup
- Modify: `pyproject.toml` — add `observability` extra + add `opentelemetry-sdk` to `dev`
- Modify: `README.md` — short Observability section
- Create: `tests/test_observability/__init__.py`
- Create: `tests/test_observability/test_facade.py` — disabled/no-op + import isolation + content gate
- Create: `tests/test_observability/test_spans.py` — span tree + attributes via `InMemorySpanExporter`
- Create: `tests/test_observability/test_engine_tracing.py` — end-to-end via `QueryEngine`

---

## Task 1: Tracing setup module (`tracing.py`)

**Files:**
- Create: `src/openharness/observability/tracing.py`
- Create: `src/openharness/observability/__init__.py`
- Test: `tests/test_observability/test_facade.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_observability/__init__.py` (empty file).

Create `tests/test_observability/test_facade.py`:

```python
"""Tests for the observability facade: disabled/no-op behavior."""
from __future__ import annotations

import subprocess
import sys

import pytest


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing()
    assert tracing.is_enabled() is False
    assert tracing.get_tracer() is None


def test_none_exporter_stays_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing()
    assert tracing.is_enabled() is False


def test_importing_facade_does_not_import_opentelemetry():
    # Run in a clean subprocess so other tests' imports don't pollute sys.modules.
    code = (
        "import sys; import openharness.observability as obs; "
        "obs.init_tracing(); "
        "assert 'opentelemetry' not in sys.modules, sorted(m for m in sys.modules if 'opentel' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability/test_facade.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openharness.observability'`

- [ ] **Step 3: Write minimal implementation**

Create `src/openharness/observability/tracing.py`:

```python
"""OpenTelemetry tracer setup — disabled unless an exporter is selected.

The OpenTelemetry packages are imported lazily inside ``init_tracing`` so that
importing this module (and ``openharness.observability``) never pulls in the SDK.
When no exporter is configured ``get_tracer()`` returns ``None`` and every span
helper degrades to a no-op.
"""
from __future__ import annotations

import os
from typing import Any

_initialized = False
_tracer: Any = None


def init_tracing() -> None:
    """Configure a global tracer provider from OTEL_* env vars (idempotent).

    Off unless ``OTEL_TRACES_EXPORTER`` is ``console`` or ``otlp``. Silently
    no-ops if the OpenTelemetry SDK (or OTLP exporter) is not installed.
    """
    global _initialized, _tracer
    if _initialized:
        return
    _initialized = True

    exporter_name = os.environ.get("OTEL_TRACES_EXPORTER", "none").strip().lower()
    if exporter_name in ("", "none"):
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        return

    if exporter_name == "console":
        exporter: Any = ConsoleSpanExporter()
    elif exporter_name == "otlp":
        exporter = _build_otlp_exporter()
        if exporter is None:
            return
    else:
        return

    try:
        from openharness import __version__ as version
    except Exception:
        version = "unknown"

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "openharness"),
            "service.version": version,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = provider.get_tracer("openharness")


def _build_otlp_exporter() -> Any:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    except ImportError:
        pass
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    except ImportError:
        return None


def get_tracer() -> Any:
    """Return the active tracer, or ``None`` when tracing is disabled."""
    return _tracer


def is_enabled() -> bool:
    """Whether tracing is active."""
    return _tracer is not None


def use_tracer_provider(provider: Any) -> None:
    """Test hook: install a tracer provider (e.g. with an in-memory exporter)."""
    global _initialized, _tracer
    _initialized = True
    _tracer = provider.get_tracer("openharness")


def reset_tracing() -> None:
    """Test hook: disable tracing again."""
    global _initialized, _tracer
    _initialized = False
    _tracer = None
```

Create `src/openharness/observability/__init__.py`:

```python
"""Observability: OpenTelemetry tracing for the agent loop."""
from __future__ import annotations

from openharness.observability.tracing import (
    get_tracer,
    init_tracing,
    is_enabled,
    reset_tracing,
    use_tracer_provider,
)

__all__ = [
    "get_tracer",
    "init_tracing",
    "is_enabled",
    "reset_tracing",
    "use_tracer_provider",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability/test_facade.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/openharness/observability/__init__.py src/openharness/observability/tracing.py tests/test_observability/
git commit -m "feat(observability): OTel tracer setup with env-selectable exporter"
```

---

## Task 2: Span helpers (`spans.py`)

**Files:**
- Create: `src/openharness/observability/spans.py`
- Modify: `src/openharness/observability/__init__.py` (re-export span helpers)
- Test: `tests/test_observability/test_spans.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_observability/test_spans.py`:

```python
"""Tests for span helpers: tree shape, attributes, content gate."""
from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from openharness.api.usage import UsageSnapshot
from openharness.observability import spans, tracing


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracing.use_tracer_provider(provider)
    yield exp
    tracing.reset_tracing()


def _by_name(finished):
    return {s.name: s for s in finished}


def test_span_tree_parenting(exporter):
    with spans.user_input_span(session_id="sess-1", conversation_id="sess-1", model="m", entrypoint="cli"):
        with spans.turn_span(1):
            with spans.model_call_span("m") as chat:
                chat.record_usage(UsageSnapshot(input_tokens=7, output_tokens=3), stop_reason="tool_use")
            with spans.tool_span(tool_name="bash", tool_call_id="t1", tool_input={"command": "ls"}) as tool:
                tool.record_tool_result("file1\n", is_error=False)

    finished = exporter.get_finished_spans()
    names = _by_name(finished)
    assert set(names) == {"user_input", "turn", "chat m", "execute_tool bash"}

    root = names["user_input"]
    turn = names["turn"]
    chat = names["chat m"]
    tool = names["execute_tool bash"]

    assert root.parent is None
    assert turn.parent.span_id == root.context.span_id
    assert chat.parent.span_id == turn.context.span_id
    assert tool.parent.span_id == turn.context.span_id


def test_span_attributes(exporter):
    with spans.user_input_span(session_id="s", conversation_id="s", model="claude-x", entrypoint="cli"):
        with spans.turn_span(2):
            with spans.model_call_span("claude-x") as chat:
                chat.record_usage(UsageSnapshot(input_tokens=11, output_tokens=4), stop_reason="end_turn")
            with spans.tool_span(tool_name="grep", tool_call_id="t2", tool_input={"pattern": "x"}) as tool:
                tool.record_tool_result("hit", is_error=True)

    names = _by_name(exporter.get_finished_spans())
    chat = names["chat claude-x"].attributes
    assert chat["gen_ai.operation.name"] == "chat"
    assert chat["gen_ai.request.model"] == "claude-x"
    assert chat["gen_ai.usage.input_tokens"] == 11
    assert chat["gen_ai.usage.output_tokens"] == 4
    assert chat["gen_ai.response.finish_reasons"] == ("end_turn",)

    tool = names["execute_tool grep"].attributes
    assert tool["gen_ai.tool.name"] == "grep"
    assert tool["gen_ai.tool.call.id"] == "t2"
    assert tool["openharness.tool.is_error"] is True
    assert tool["openharness.tool.output.length"] == 3


def test_content_gate_off_by_default(exporter, monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    with spans.tool_span(tool_name="bash", tool_call_id="t", tool_input={"command": "secret"}) as tool:
        tool.record_tool_result("sensitive output", is_error=False)
    tool_attrs = _by_name(exporter.get_finished_spans())["execute_tool bash"].attributes
    assert "openharness.tool.input" not in tool_attrs
    assert "openharness.tool.output" not in tool_attrs


def test_content_gate_on_captures_payload(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    with spans.tool_span(tool_name="bash", tool_call_id="t", tool_input={"command": "echo hi"}) as tool:
        tool.record_tool_result("hi", is_error=False)
    tool_attrs = _by_name(exporter.get_finished_spans())["execute_tool bash"].attributes
    assert "echo hi" in tool_attrs["openharness.tool.input"]
    assert tool_attrs["openharness.tool.output"] == "hi"


def test_error_status_recorded(exporter):
    from opentelemetry.trace import StatusCode

    with pytest.raises(RuntimeError):
        with spans.model_call_span("m"):
            raise RuntimeError("boom")
    span = _by_name(exporter.get_finished_spans())["chat m"]
    assert span.status.status_code == StatusCode.ERROR


def test_noop_when_disabled():
    tracing.reset_tracing()
    # No provider installed -> helpers run without error and create no spans.
    with spans.user_input_span(session_id="s", conversation_id="s", model="m", entrypoint="cli"):
        with spans.model_call_span("m") as chat:
            chat.record_usage(UsageSnapshot(input_tokens=1, output_tokens=1), stop_reason="end_turn")
    assert tracing.get_tracer() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability/test_spans.py -v`
Expected: FAIL — `ImportError: cannot import name 'spans'` (or `AttributeError` on `spans.user_input_span`)

- [ ] **Step 3: Write minimal implementation**

Create `src/openharness/observability/spans.py`:

```python
"""Span helpers for the agent loop.

Every helper is a context manager that yields a small ``_Span`` wrapper. When
tracing is disabled (no tracer configured) the helpers are cheap no-ops and the
OpenTelemetry packages are never imported.

Span parenting uses an explicit ``contextvars`` parent (linked via
``set_span_in_context``) rather than OpenTelemetry's ambient "current span".
``run_query`` is an async generator that yields control mid-turn and runs tools
concurrently via ``asyncio.gather``; contextvars are copied into child tasks at
creation, so the explicit parent keeps the tree correct across both boundaries.
"""
from __future__ import annotations

import contextvars
import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

from openharness.observability.tracing import get_tracer

_current_span: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "openharness_current_span", default=None
)

_CONTENT_LIMIT = 8192


def capture_content_enabled() -> bool:
    """Whether prompt / tool payloads may be attached to spans."""
    val = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "")
    return val.strip().lower() in ("true", "1", "yes", "on")


class _Span:
    """Thin wrapper; all methods are no-ops when the underlying span is None."""

    def __init__(self, span: Any) -> None:
        self._span = span

    def set(self, key: str, value: Any) -> None:
        if self._span is None or value is None:
            return
        try:
            self._span.set_attribute(key, value)
        except Exception:
            pass

    def record_usage(self, usage: Any, stop_reason: str | None = None) -> None:
        self.set("gen_ai.usage.input_tokens", getattr(usage, "input_tokens", None))
        self.set("gen_ai.usage.output_tokens", getattr(usage, "output_tokens", None))
        if stop_reason:
            self.set("gen_ai.response.finish_reasons", [stop_reason])

    def record_tool_result(self, output: str, is_error: bool) -> None:
        self.set("openharness.tool.is_error", is_error)
        self.set("openharness.tool.output.length", len(output or ""))
        if capture_content_enabled():
            self.set("openharness.tool.output", (output or "")[:_CONTENT_LIMIT])

    def record_error(self, exc: BaseException) -> None:
        if self._span is None:
            return
        try:
            from opentelemetry.trace import Status, StatusCode

            self._span.record_exception(exc)
            self._span.set_status(Status(StatusCode.ERROR, str(exc)))
        except Exception:
            pass


@contextmanager
def _span(name: str, attrs: dict[str, Any] | None = None) -> Iterator[_Span]:
    tracer = get_tracer()
    if tracer is None:
        yield _Span(None)
        return

    from opentelemetry import trace

    parent = _current_span.get()
    ctx = trace.set_span_in_context(parent) if parent is not None else None
    span = tracer.start_span(name, context=ctx)
    if attrs:
        for key, value in attrs.items():
            if value is not None:
                try:
                    span.set_attribute(key, value)
                except Exception:
                    pass
    token = _current_span.set(span)
    try:
        yield _Span(span)
    except BaseException as exc:
        try:
            from opentelemetry.trace import Status, StatusCode

            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
        except Exception:
            pass
        raise
    finally:
        _current_span.reset(token)
        try:
            span.end()
        except Exception:
            pass


def user_input_span(*, session_id: str, conversation_id: str, model: str, entrypoint: str):
    return _span(
        "user_input",
        {
            "openharness.session.id": session_id or None,
            "openharness.conversation.id": conversation_id or None,
            "gen_ai.request.model": model,
            "openharness.entrypoint": entrypoint,
        },
    )


def turn_span(index: int):
    return _span("turn", {"openharness.turn.index": index})


def model_call_span(model: str, system: str = "anthropic"):
    return _span(
        f"chat {model}",
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.system": system,
            "gen_ai.request.model": model,
        },
    )


@contextmanager
def tool_span(*, tool_name: str, tool_call_id: str, tool_input: dict[str, Any]) -> Iterator[_Span]:
    attrs = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool_name,
        "gen_ai.tool.call.id": tool_call_id,
    }
    with _span(f"execute_tool {tool_name}", attrs) as handle:
        if capture_content_enabled():
            try:
                handle.set(
                    "openharness.tool.input",
                    json.dumps(tool_input, default=str)[:_CONTENT_LIMIT],
                )
            except Exception:
                pass
        yield handle
```

Update `src/openharness/observability/__init__.py` to also re-export the span helpers:

```python
"""Observability: OpenTelemetry tracing for the agent loop."""
from __future__ import annotations

from openharness.observability.spans import (
    capture_content_enabled,
    model_call_span,
    tool_span,
    turn_span,
    user_input_span,
)
from openharness.observability.tracing import (
    get_tracer,
    init_tracing,
    is_enabled,
    reset_tracing,
    use_tracer_provider,
)

__all__ = [
    "capture_content_enabled",
    "get_tracer",
    "init_tracing",
    "is_enabled",
    "model_call_span",
    "reset_tracing",
    "tool_span",
    "turn_span",
    "use_tracer_provider",
    "user_input_span",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_observability/test_spans.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/openharness/observability/spans.py src/openharness/observability/__init__.py tests/test_observability/test_spans.py
git commit -m "feat(observability): span helpers with explicit parenting + content gate"
```

---

## Task 3: Wire spans into the engine

**Files:**
- Modify: `src/openharness/engine/query.py` (turn span, model-call span, tool spans)
- Modify: `src/openharness/engine/query_engine.py` (root `user_input` span)
- Test: `tests/test_observability/test_engine_tracing.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_observability/test_engine_tracing.py`:

```python
"""End-to-end engine tracing: full span tree via the QueryEngine."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from openharness.api.client import ApiMessageCompleteEvent
from openharness.api.errors import RequestFailure
from openharness.api.usage import UsageSnapshot
from openharness.config.settings import PermissionSettings
from openharness.engine.messages import ConversationMessage, TextBlock, ToolUseBlock
from openharness.engine.query_engine import QueryEngine
from openharness.observability import tracing
from openharness.permissions import PermissionChecker, PermissionMode
from openharness.tools import create_default_tool_registry
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from pydantic import BaseModel


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracing.use_tracer_provider(provider)
    yield exp
    tracing.reset_tracing()


class _FakeApiClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def stream_message(self, request):
        del request
        message, usage = self._responses.pop(0)
        yield ApiMessageCompleteEvent(message=message, usage=usage, stop_reason=None)


class _FailingApiClient:
    async def stream_message(self, request):
        del request
        raise RequestFailure("network down")
        yield  # pragma: no cover  (make this an async generator)


class _OkInput(BaseModel):
    pass


class _OkTool(BaseTool):
    name = "ok_tool"
    description = "ok"
    input_model = _OkInput

    def is_read_only(self, arguments: BaseModel) -> bool:
        return True

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        del arguments, context
        return ToolResult(output="ok")


def _spans_by_name(exporter):
    out: dict[str, list] = {}
    for s in exporter.get_finished_spans():
        out.setdefault(s.name, []).append(s)
    return out


@pytest.mark.asyncio
async def test_engine_emits_full_trace_tree(exporter, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_COORDINATOR_MODE", raising=False)
    registry = ToolRegistry()
    registry.register(_OkTool())
    engine = QueryEngine(
        api_client=_FakeApiClient(
            [
                (
                    ConversationMessage(
                        role="assistant",
                        content=[ToolUseBlock(id="t1", name="ok_tool", input={})],
                    ),
                    UsageSnapshot(input_tokens=4, output_tokens=2),
                ),
                (
                    ConversationMessage(role="assistant", content=[TextBlock(text="done")]),
                    UsageSnapshot(input_tokens=8, output_tokens=6),
                ),
            ]
        ),
        tool_registry=registry,
        permission_checker=PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)),
        cwd=tmp_path,
        model="claude-test",
        system_prompt="system",
        tool_metadata={"session_id": "sess-9"},
    )

    _ = [event async for event in engine.submit_message("do it")]

    by_name = _spans_by_name(exporter)
    assert len(by_name["user_input"]) == 1
    assert len(by_name["turn"]) == 2  # tool turn + final text turn
    assert len(by_name["chat claude-test"]) == 2
    assert len(by_name["execute_tool ok_tool"]) == 1

    root = by_name["user_input"][0]
    assert root.parent is None
    assert root.attributes["openharness.session.id"] == "sess-9"
    assert root.attributes["openharness.entrypoint"] == "cli"

    # tool span is a child of a turn span, not of the chat span.
    tool = by_name["execute_tool ok_tool"][0]
    turn_ids = {t.context.span_id for t in by_name["turn"]}
    assert tool.parent.span_id in turn_ids


@pytest.mark.asyncio
async def test_engine_records_error_on_api_failure(exporter, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_COORDINATOR_MODE", raising=False)
    engine = QueryEngine(
        api_client=_FailingApiClient(),
        tool_registry=ToolRegistry(),
        permission_checker=PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)),
        cwd=tmp_path,
        model="claude-test",
        system_prompt="system",
        max_turns=1,
        tool_metadata={"session_id": "sess-err"},
    )

    _ = [event async for event in engine.submit_message("boom")]

    by_name = _spans_by_name(exporter)
    chat = by_name["chat claude-test"][0]
    assert chat.status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_engine_concurrent_tools_share_turn_parent(exporter, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_COORDINATOR_MODE", raising=False)
    registry = ToolRegistry()
    registry.register(_OkTool())
    engine = QueryEngine(
        api_client=_FakeApiClient(
            [
                (
                    ConversationMessage(
                        role="assistant",
                        content=[
                            ToolUseBlock(id="a", name="ok_tool", input={}),
                            ToolUseBlock(id="b", name="ok_tool", input={}),
                        ],
                    ),
                    UsageSnapshot(input_tokens=1, output_tokens=1),
                ),
                (
                    ConversationMessage(role="assistant", content=[TextBlock(text="done")]),
                    UsageSnapshot(input_tokens=1, output_tokens=1),
                ),
            ]
        ),
        tool_registry=registry,
        permission_checker=PermissionChecker(PermissionSettings(mode=PermissionMode.FULL_AUTO)),
        cwd=tmp_path,
        model="claude-test",
        system_prompt="system",
        tool_metadata={"session_id": "sess-par"},
    )

    _ = [event async for event in engine.submit_message("run both")]

    by_name = _spans_by_name(exporter)
    tools = by_name["execute_tool ok_tool"]
    assert len(tools) == 2
    parent_ids = {t.parent.span_id for t in tools}
    assert len(parent_ids) == 1  # both children of the same turn span
    turn_ids = {t.context.span_id for t in by_name["turn"]}
    assert parent_ids.issubset(turn_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_observability/test_engine_tracing.py -v`
Expected: FAIL — assertions on span names (no spans are produced yet; `by_name["user_input"]` raises `KeyError`).

- [ ] **Step 3a: Add the root span in `query_engine.py`**

In `src/openharness/engine/query_engine.py`, add the import near the other engine imports (after line 17, `from openharness.services.autodream.service import schedule_auto_dream`):

```python
from openharness import observability as obs
```

In `submit_message`, replace the existing `try/finally` block (currently lines 336-346):

```python
        try:
            async for event, usage in run_query(context, query_messages):
                if isinstance(event, AssistantTurnComplete):
                    self._messages = list(query_messages)
                if usage is not None:
                    self._cost_tracker.add(usage)
                yield event
        finally:
            await self._update_session_memory()
            await self._extract_durable_memories()
            self._schedule_auto_dream()
```

with:

```python
        try:
            with obs.user_input_span(
                session_id=str(self._tool_metadata.get("session_id") or ""),
                conversation_id=str(
                    self._tool_metadata.get("conversation_id")
                    or self._tool_metadata.get("session_id")
                    or ""
                ),
                model=self._model,
                entrypoint=str(self._tool_metadata.get("entrypoint") or "cli"),
            ):
                async for event, usage in run_query(context, query_messages):
                    if isinstance(event, AssistantTurnComplete):
                        self._messages = list(query_messages)
                    if usage is not None:
                        self._cost_tracker.add(usage)
                    yield event
        finally:
            await self._update_session_memory()
            await self._extract_durable_memories()
            self._schedule_auto_dream()
```

In `continue_pending`, replace the existing loop (currently lines 369-372):

```python
        async for event, usage in run_query(context, self._messages):
            if usage is not None:
                self._cost_tracker.add(usage)
            yield event
        await self._update_session_memory()
        await self._extract_durable_memories()
```

with:

```python
        with obs.user_input_span(
            session_id=str(self._tool_metadata.get("session_id") or ""),
            conversation_id=str(
                self._tool_metadata.get("conversation_id")
                or self._tool_metadata.get("session_id")
                or ""
            ),
            model=self._model,
            entrypoint=str(self._tool_metadata.get("entrypoint") or "cli"),
        ):
            async for event, usage in run_query(context, self._messages):
                if usage is not None:
                    self._cost_tracker.add(usage)
                yield event
        await self._update_session_memory()
        await self._extract_durable_memories()
```

- [ ] **Step 3b: Add turn, model-call, and tool spans in `query.py`**

In `src/openharness/engine/query.py`, add the import near the top engine imports (alongside the `stream_events` import around line 30):

```python
from openharness import observability as obs
```

**(i) Turn span — wrap the turn body.** The turn body currently runs from the line `final_message: ConversationMessage | None = None` (line 724) through `messages.append(ConversationMessage(role="user", content=tool_results))` (line 880). Wrap that entire region in `with obs.turn_span(turn_count):`, indenting the enclosed lines one level (4 spaces). No logic inside changes except the two insertions below. After the change, the structure is:

```python
        # ---------------------------------------------------------------

        # --- image preprocessing (unchanged, stays OUTSIDE the turn span) ---
        async for event in _preprocess_images_in_messages(messages, context):
            yield event, None
        # -----------------------------------------------------------------------------

        with obs.turn_span(turn_count):
            final_message: ConversationMessage | None = None
            usage = UsageSnapshot()
            stop_reason: str | None = None

            with obs.model_call_span(context.model) as model_span:
                try:
                    async for event in context.api_client.stream_message(
                        ApiMessageRequest(
                            model=context.model,
                            messages=messages,
                            system_prompt=context.system_prompt,
                            max_tokens=effective_max_tokens,
                            tools=context.tool_registry.to_api_schema(),
                            effort=context.effort,
                        )
                    ):
                        if isinstance(event, ApiTextDeltaEvent):
                            yield AssistantTextDelta(text=event.text), None
                            continue
                        if isinstance(event, ApiRetryEvent):
                            yield StatusEvent(
                                message=(
                                    f"Request failed; retrying in {event.delay_seconds:.1f}s "
                                    f"(attempt {event.attempt + 1} of {event.max_attempts}): {event.message}"
                                )
                            ), None
                            continue

                        if isinstance(event, ApiMessageCompleteEvent):
                            final_message = event.message
                            usage = event.usage
                            stop_reason = event.stop_reason
                except Exception as exc:
                    model_span.record_error(exc)
                    error_msg = str(exc)
                    if _is_completion_token_limit_error(exc):
                        supported_limit = _extract_completion_token_limit(exc)
                        if supported_limit is not None and effective_max_tokens > supported_limit:
                            previous_max_tokens = effective_max_tokens
                            effective_max_tokens = supported_limit
                            yield StatusEvent(
                                message=(
                                    f"Model rejected max_tokens={previous_max_tokens}; "
                                    f"retrying with provider limit {effective_max_tokens}."
                                )
                            ), None
                            turn_count = max(0, turn_count - 1)
                            continue
                    if not reactive_compact_attempted and _is_prompt_too_long_error(exc):
                        reactive_compact_attempted = True
                        yield StatusEvent(message=REACTIVE_COMPACT_STATUS_MESSAGE), None
                        async for event, usage in _stream_compaction(trigger="reactive", force=True):
                            yield event, usage
                        compacted_messages, was_compacted = last_compaction_result
                        if compacted_messages is not messages:
                            messages[:] = compacted_messages
                        if was_compacted:
                            continue
                    if "connect" in error_msg.lower() or "timeout" in error_msg.lower() or "network" in error_msg.lower():
                        yield ErrorEvent(message=f"Network error: {error_msg}. Check your internet connection and try again."), None
                    else:
                        yield ErrorEvent(message=f"API error: {error_msg}"), None
                    return
                else:
                    model_span.record_usage(usage, stop_reason)

            if final_message is None:
                raise RuntimeError("Model stream finished without a final message")

            # ... (rest of the turn body — coordinator context, append final_message,
            #      AssistantTurnComplete, stop-hook, tool dispatch — unchanged except
            #      the tool-span insertions in (iii) below) ...
```

> Note the `continue`/`return` statements inside the `except` block now exit both
> the `model_call_span` and the `turn_span` context managers cleanly (the span
> helpers end the span in their `finally`). The `else:` clause records usage only
> on a successful stream. `effective_max_tokens`, `reactive_compact_attempted`,
> `turn_count`, and `last_compaction_result` are defined in the enclosing
> `run_query` scope and remain assignable (they are not rebound as locals).

**(ii) Capture `stop_reason`** — already shown above (`stop_reason = event.stop_reason` on the `ApiMessageCompleteEvent` branch, and `model_span.record_usage(usage, stop_reason)` in the `else`).

**(iii) Tool spans.** In the single-tool branch, wrap the call. Replace (currently lines 821-840):

```python
        if len(tool_calls) == 1:
            # Single tool: sequential (stream events immediately)
            tc = tool_calls[0]
            yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
            try:
                result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
            except Exception as exc:
                log.exception("tool execution raised: name=%s id=%s", tc.name, tc.id)
                result = ToolResultBlock(
                    tool_use_id=tc.id,
                    content=f"Tool {tc.name} failed: {type(exc).__name__}: {exc}",
                    is_error=True,
                )
            yield ToolExecutionCompleted(
                tool_name=tc.name,
                output=result.content,
                is_error=result.is_error,
                metadata=result.result_metadata,
            ), None
            tool_results = [result]
```

with (note: everything is one level deeper because of the turn span wrapper):

```python
            if len(tool_calls) == 1:
                # Single tool: sequential (stream events immediately)
                tc = tool_calls[0]
                yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input), None
                with obs.tool_span(tool_name=tc.name, tool_call_id=tc.id, tool_input=tc.input) as tool_handle:
                    try:
                        result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
                    except Exception as exc:
                        log.exception("tool execution raised: name=%s id=%s", tc.name, tc.id)
                        result = ToolResultBlock(
                            tool_use_id=tc.id,
                            content=f"Tool {tc.name} failed: {type(exc).__name__}: {exc}",
                            is_error=True,
                        )
                    tool_handle.record_tool_result(result.content, result.is_error)
                yield ToolExecutionCompleted(
                    tool_name=tc.name,
                    output=result.content,
                    is_error=result.is_error,
                    metadata=result.result_metadata,
                ), None
                tool_results = [result]
```

In the concurrent branch, wrap inside `_run`. Replace (currently lines 846-847):

```python
            async def _run(tc):
                return await _execute_tool_call(context, tc.name, tc.id, tc.input)
```

with:

```python
            async def _run(tc):
                with obs.tool_span(tool_name=tc.name, tool_call_id=tc.id, tool_input=tc.input) as tool_handle:
                    result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
                    tool_handle.record_tool_result(result.content, result.is_error)
                    return result
```

> The concurrent tasks created by `asyncio.gather` copy the current `contextvars`
> at creation, so each `_run` task sees the turn span as `_current_span` and its
> tool span is parented correctly. If `_execute_tool_call` raises, the exception
> propagates out of the `tool_span` (recording ERROR status on the span) and is
> caught by `gather(return_exceptions=True)`, exactly as before.

- [ ] **Step 4: Run the tracing tests + the full engine suite**

Run: `pytest tests/test_observability/ tests/test_engine/ -v`
Expected: PASS — new tracing tests pass AND all pre-existing engine tests still pass (the turn-span reindent must not change behavior).

- [ ] **Step 5: Commit**

```bash
git add src/openharness/engine/query.py src/openharness/engine/query_engine.py tests/test_observability/test_engine_tracing.py
git commit -m "feat(observability): emit OTel spans from the agent loop"
```

---

## Task 4: Initialize tracing at CLI startup + packaging + docs

**Files:**
- Modify: `src/openharness/cli.py:2376` (next to existing logging setup)
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Inspect the CLI logging setup**

Run: `sed -n '2370,2390p' src/openharness/cli.py`
Expected: shows the `logging.basicConfig(...)` block (around lines 2376-2384).

- [ ] **Step 2: Add `init_tracing()` call**

In `src/openharness/cli.py`, immediately AFTER the logging configuration block (after line 2384, the `logging.basicConfig(level=lvl, ...)` call), add:

```python
    from openharness import observability as obs

    obs.init_tracing()
```

(Placed so it runs once at startup. It is a no-op unless `OTEL_TRACES_EXPORTER` is set.)

- [ ] **Step 3: Add the `observability` extra and dev dep in `pyproject.toml`**

In `[project.optional-dependencies]`, add a new extra (after the `agentbase` extra):

```toml
observability = [
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp>=1.20",
]
```

And add `opentelemetry-sdk>=1.20` to the existing `dev` list (so the test suite can run the tracing tests in CI):

```toml
dev = [
    "pexpect>=4.9.0",
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.5.0",
    "mypy>=1.10.0",
    "opentelemetry-sdk>=1.20",
]
```

- [ ] **Step 4: Install the new dev dependency**

Run: `uv pip install -e '.[dev,observability]'`
Expected: installs `opentelemetry-sdk` and `opentelemetry-exporter-otlp` (and deps) into the venv.

- [ ] **Step 5: Add a README section**

In `README.md`, after the "Harness Flow" subsection (the mermaid diagram block, around line 487-505), add:

```markdown
### Observability (OpenTelemetry)

The agent loop is instrumented with OpenTelemetry. Tracing is **off by default**;
enable it with the standard `OTEL_*` environment variables and the optional extra:

```bash
pip install 'openharness-ai[observability]'

# Print spans to the console:
OTEL_TRACES_EXPORTER=console oh

# Or send them to a local Jaeger / OTLP collector:
OTEL_TRACES_EXPORTER=otlp OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 oh
```

Each user input produces one trace: `user_input → turn → {chat, execute_tool}`,
with token usage, finish reasons, tool names, errors, and timings. Prompt and
tool-I/O payloads are attached only when
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`.
```

- [ ] **Step 6: Verify the whole suite + lint/type checks**

Run: `pytest tests/test_observability/ tests/test_engine/ -q && ruff check src/openharness/observability && mypy src/openharness/observability`
Expected: tests PASS; ruff clean; mypy clean.

- [ ] **Step 7: Commit**

```bash
git add src/openharness/cli.py pyproject.toml README.md
git commit -m "feat(observability): init tracing at CLI startup + packaging extra + docs"
```

---

## Self-Review

**Spec coverage:**
- OTel spans, turn/model/tool tree → Task 3 ✓
- Exporter env-selectable (console/otlp/none, off by default) → Task 1 ✓
- Content gate via `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` → Task 2 ✓
- Explicit parent propagation for concurrency/yields → Task 2 (`_current_span` + `set_span_in_context`) + Task 3 concurrent test ✓
- No mandatory deps; optional extra; no-op when absent → Task 1 (lazy import) + Task 4 (extra) + import-isolation test ✓
- `init_tracing()` at CLI startup → Task 4 ✓
- Safety: telemetry never breaks a turn; program exceptions re-raised → `_Span` swallows; `_span` re-raises after recording ✓
- Test plan items 1-6 → all covered across `test_facade.py`, `test_spans.py`, `test_engine_tracing.py` ✓

**Placeholder scan:** none — all code shown in full; the one reindent (turn body) is bounded by exact anchor lines with the changed regions shown in full.

**Type/name consistency:** facade names (`init_tracing`, `is_enabled`, `get_tracer`, `use_tracer_provider`, `reset_tracing`, `user_input_span`, `turn_span`, `model_call_span`, `tool_span`, `capture_content_enabled`) and `_Span` methods (`set`, `record_usage`, `record_tool_result`, `record_error`) are used identically in tests and engine wiring. `obs` alias used consistently. `stop_reason` sourced from `ApiMessageCompleteEvent.stop_reason` (confirmed present in `api/client.py`).
