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
