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
    CompactProgressEvent,
)
from openharness.engine.messages import ConversationMessage, TextBlock
from openharness.api.usage import UsageSnapshot


def test_text_delta_becomes_artifact_chunk():
    intent = map_stream_event(AssistantTextDelta(text="hello"))
    assert isinstance(intent, ArtifactChunk)
    assert intent.text == "hello"


def test_tool_start_becomes_status():
    intent = map_stream_event(ToolExecutionStarted(tool_name="bash", tool_input={}))
    assert isinstance(intent, StatusUpdate)
    assert "bash" in intent.text
    assert intent.metadata == {"type": "tool", "tool": "bash", "phase": "start"}


def test_tool_completed_becomes_status():
    intent = map_stream_event(
        ToolExecutionCompleted(tool_name="bash", output="x", is_error=False, metadata={})
    )
    assert isinstance(intent, StatusUpdate)
    assert intent.metadata == {
        "type": "tool",
        "tool": "bash",
        "phase": "end",
        "is_error": False,
    }


def test_status_event_becomes_status():
    intent = map_stream_event(StatusEvent(message="compacting"))
    assert isinstance(intent, StatusUpdate)
    assert intent.metadata == {"type": "status"}


def test_error_event_becomes_failure():
    intent = map_stream_event(ErrorEvent(message="boom"))
    assert isinstance(intent, Failure)
    assert "boom" in intent.text


def test_tool_completed_with_error_contains_warning_symbol():
    intent = map_stream_event(
        ToolExecutionCompleted(tool_name="bash", output="err", is_error=True, metadata={})
    )
    assert isinstance(intent, StatusUpdate)
    assert "⚠️" in intent.text


def test_compact_progress_event_becomes_status():
    intent = map_stream_event(
        CompactProgressEvent(phase="compact_start", trigger="auto")
    )
    assert isinstance(intent, StatusUpdate)


def test_assistant_turn_complete_returns_none():
    message = ConversationMessage(role="assistant", content=[TextBlock(text="x")])
    usage = UsageSnapshot()
    assert map_stream_event(AssistantTurnComplete(message=message, usage=usage)) is None
