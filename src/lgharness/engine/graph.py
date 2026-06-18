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
