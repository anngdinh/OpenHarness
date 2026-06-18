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
