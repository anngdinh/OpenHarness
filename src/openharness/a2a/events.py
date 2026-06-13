"""Map harness StreamEvents to SDK-agnostic A2A intent descriptors."""

from __future__ import annotations

from dataclasses import dataclass

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
    """A human-readable progress message (task stays `working`)."""

    text: str


@dataclass(frozen=True)
class Failure:
    """The run failed."""

    text: str


A2AIntent = ArtifactChunk | StatusUpdate | Failure


def map_stream_event(event: StreamEvent) -> A2AIntent | None:
    """Translate one harness StreamEvent into an A2A intent (or None to skip)."""
    if isinstance(event, AssistantTextDelta):
        return ArtifactChunk(text=event.text)
    if isinstance(event, ToolExecutionStarted):
        return StatusUpdate(text=f"\U0001f527 {event.tool_name}…")
    if isinstance(event, ToolExecutionCompleted):
        mark = "⚠️" if event.is_error else "✓"
        return StatusUpdate(text=f"{mark} {event.tool_name}")
    if isinstance(event, (StatusEvent, CompactProgressEvent)):
        return StatusUpdate(text=getattr(event, "message", "") or "working…")
    if isinstance(event, ErrorEvent):
        return Failure(text=event.message)
    if isinstance(event, AssistantTurnComplete):
        return None
    return None
