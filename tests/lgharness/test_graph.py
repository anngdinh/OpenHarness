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
