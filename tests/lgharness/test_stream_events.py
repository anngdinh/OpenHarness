from lgharness.engine.stream_events import (
    AssistantMessage,
    ErrorEvent,
    PermissionRequest,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from lgharness.prompts.system_prompt import build_system_prompt


def test_event_fields():
    assert AssistantMessage(text="hi").text == "hi"
    assert ToolExecutionStarted(tool_name="bash", tool_input={"command": "ls"}).tool_name == "bash"
    c = ToolExecutionCompleted(tool_name="bash", output="ok")
    assert c.is_error is False
    assert PermissionRequest(requests=[{"id": "1", "name": "bash", "args": {}}]).requests[0]["name"] == "bash"
    assert ErrorEvent(message="boom").message == "boom"


def test_system_prompt_mentions_tools_and_cwd():
    p = build_system_prompt("/tmp/work")
    assert "/tmp/work" in p
    for name in ("read_file", "write_file", "bash"):
        assert name in p
