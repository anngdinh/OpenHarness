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
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Iterator

from openharness.observability.tracing import capture_content_enabled, get_tracer

_current_span: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "openharness_current_span", default=None
)

# Max chars per captured content field; None = no cap (capture full content).
_CONTENT_LIMIT: int | None = None


def _clip(text: str) -> str:
    if _CONTENT_LIMIT is None:
        return text
    return text[:_CONTENT_LIMIT]


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
            self.set("openharness.tool.output", _clip(output or ""))

    def record_completion(self, text: str) -> None:
        if text and capture_content_enabled():
            self.set("gen_ai.completion", _clip(text))

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


@contextmanager
def user_input_span(
    *, session_id: str, conversation_id: str, model: str, entrypoint: str, prompt: str = ""
) -> Iterator[_Span]:
    attrs = {
        "openharness.session.id": session_id or None,
        "openharness.conversation.id": conversation_id or None,
        "gen_ai.request.model": model,
        "openharness.entrypoint": entrypoint,
    }
    with _span("user_input", attrs) as handle:
        if prompt and capture_content_enabled():
            handle.set("gen_ai.prompt", _clip(prompt))
        yield handle


def turn_span(index: int) -> AbstractContextManager[_Span]:
    return _span("turn", {"openharness.turn.index": index})


def model_call_span(model: str, system: str = "anthropic") -> AbstractContextManager[_Span]:
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
                handle.set("openharness.tool.input", _clip(json.dumps(tool_input, default=str)))
            except Exception:
                pass
        yield handle
