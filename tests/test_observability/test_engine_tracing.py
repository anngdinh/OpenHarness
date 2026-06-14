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
