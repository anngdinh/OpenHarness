"""Map harness StreamEvents to SDK-agnostic A2A intent descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    CompactProgressEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


@dataclass(frozen=True)
class ArtifactChunk:
    """A piece of the streamed final answer."""

    text: str


@dataclass(frozen=True)
class StatusUpdate:
    """A human-readable progress message (task stays `working`).

    ``metadata`` is attached to the A2A status message so a streaming client can
    distinguish progress kinds (e.g. ``{"type": "tool", ...}``) from the answer
    artifact, instead of guessing from the text.
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Failure:
    """The run failed."""

    text: str


@dataclass(frozen=True)
class Usage:
    """Token usage for one assistant turn.

    A2A has no first-class usage field, so the executor accumulates these across
    turns and surfaces the total via the answer artifact's ``metadata`` (A2A's
    sanctioned extension carrier).
    """

    input_tokens: int
    output_tokens: int


A2AIntent = ArtifactChunk | StatusUpdate | Failure | Usage


def map_stream_event(event: StreamEvent) -> A2AIntent | None:
    """Translate one harness StreamEvent into an A2A intent (or None to skip)."""
    if isinstance(event, AssistantTextDelta):
        return ArtifactChunk(text=event.text)
    if isinstance(event, ToolExecutionStarted):
        return StatusUpdate(
            text=f"\U0001f527 {event.tool_name}…",
            metadata={"type": "tool", "tool": event.tool_name, "phase": "start"},
        )
    if isinstance(event, ToolExecutionCompleted):
        mark = "⚠️" if event.is_error else "✓"
        return StatusUpdate(
            text=f"{mark} {event.tool_name}",
            metadata={
                "type": "tool",
                "tool": event.tool_name,
                "phase": "end",
                "is_error": event.is_error,
            },
        )
    if isinstance(event, (StatusEvent, CompactProgressEvent)):
        return StatusUpdate(
            text=getattr(event, "message", "") or "working…",
            metadata={"type": "status"},
        )
    if isinstance(event, ErrorEvent):
        return Failure(text=event.message)
    if isinstance(event, AssistantTurnComplete):
        return Usage(
            input_tokens=event.usage.input_tokens,
            output_tokens=event.usage.output_tokens,
        )
    return None
