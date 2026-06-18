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
