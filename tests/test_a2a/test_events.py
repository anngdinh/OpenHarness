from openharness.a2a.events import (
    map_stream_event,
    ArtifactChunk,
    StatusUpdate,
    Failure,
)
from openharness.engine.stream_events import (
    AssistantTextDelta,
    ToolExecutionStarted,
    ToolExecutionCompleted,
    StatusEvent,
    ErrorEvent,
    AssistantTurnComplete,
)


def test_text_delta_becomes_artifact_chunk():
    intent = map_stream_event(AssistantTextDelta(text="hello"))
    assert isinstance(intent, ArtifactChunk)
    assert intent.text == "hello"


def test_tool_start_becomes_status():
    intent = map_stream_event(ToolExecutionStarted(tool_name="bash", tool_input={}))
    assert isinstance(intent, StatusUpdate)
    assert "bash" in intent.text


def test_tool_completed_becomes_status():
    intent = map_stream_event(
        ToolExecutionCompleted(tool_name="bash", output="x", is_error=False, metadata={})
    )
    assert isinstance(intent, StatusUpdate)


def test_status_event_becomes_status():
    assert isinstance(map_stream_event(StatusEvent(message="compacting")), StatusUpdate)


def test_error_event_becomes_failure():
    intent = map_stream_event(ErrorEvent(message="boom"))
    assert isinstance(intent, Failure)
    assert "boom" in intent.text
