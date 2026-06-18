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
