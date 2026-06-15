"""Tests for span helpers: tree shape, attributes, content gate."""
from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from openharness.api.usage import UsageSnapshot
from openharness.observability import spans, tracing


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exp))
    tracing.use_tracer_provider(provider)
    yield exp
    tracing.reset_tracing()


def _by_name(finished):
    return {s.name: s for s in finished}


def test_span_tree_parenting(exporter):
    with spans.user_input_span(session_id="sess-1", conversation_id="sess-1", model="m", entrypoint="cli"):
        with spans.turn_span(1):
            with spans.model_call_span("m") as chat:
                chat.record_usage(UsageSnapshot(input_tokens=7, output_tokens=3), stop_reason="tool_use")
            with spans.tool_span(tool_name="bash", tool_call_id="t1", tool_input={"command": "ls"}) as tool:
                tool.record_tool_result("file1\n", is_error=False)

    finished = exporter.get_finished_spans()
    names = _by_name(finished)
    assert set(names) == {"user_input", "turn", "chat m", "execute_tool bash"}

    root = names["user_input"]
    turn = names["turn"]
    chat = names["chat m"]
    tool = names["execute_tool bash"]

    assert root.parent is None
    assert turn.parent.span_id == root.context.span_id
    assert chat.parent.span_id == turn.context.span_id
    assert tool.parent.span_id == turn.context.span_id


def test_span_attributes(exporter):
    with spans.user_input_span(session_id="s", conversation_id="s", model="claude-x", entrypoint="cli"):
        with spans.turn_span(2):
            with spans.model_call_span("claude-x") as chat:
                chat.record_usage(UsageSnapshot(input_tokens=11, output_tokens=4), stop_reason="end_turn")
            with spans.tool_span(tool_name="grep", tool_call_id="t2", tool_input={"pattern": "x"}) as tool:
                tool.record_tool_result("hit", is_error=True)

    names = _by_name(exporter.get_finished_spans())
    chat = names["chat claude-x"].attributes
    assert chat["gen_ai.operation.name"] == "chat"
    assert chat["gen_ai.request.model"] == "claude-x"
    assert chat["gen_ai.usage.input_tokens"] == 11
    assert chat["gen_ai.usage.output_tokens"] == 4
    assert chat["gen_ai.response.finish_reasons"] == ("end_turn",)

    tool = names["execute_tool grep"].attributes
    assert tool["gen_ai.tool.name"] == "grep"
    assert tool["gen_ai.tool.call.id"] == "t2"
    assert tool["openharness.tool.is_error"] is True
    assert tool["openharness.tool.output.length"] == 3


def test_content_gate_off_by_default(exporter, monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    with spans.tool_span(tool_name="bash", tool_call_id="t", tool_input={"command": "secret"}) as tool:
        tool.record_tool_result("sensitive output", is_error=False)
    tool_attrs = _by_name(exporter.get_finished_spans())["execute_tool bash"].attributes
    assert "openharness.tool.input" not in tool_attrs
    assert "openharness.tool.output" not in tool_attrs


def test_content_gate_on_captures_payload(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    with spans.tool_span(tool_name="bash", tool_call_id="t", tool_input={"command": "echo hi"}) as tool:
        tool.record_tool_result("hi", is_error=False)
    tool_attrs = _by_name(exporter.get_finished_spans())["execute_tool bash"].attributes
    assert "echo hi" in tool_attrs["openharness.tool.input"]
    assert tool_attrs["openharness.tool.output"] == "hi"


def test_capture_prompt_and_completion(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    with spans.user_input_span(
        session_id="s", conversation_id="s", model="m", entrypoint="cli", prompt="hello world"
    ):
        with spans.model_call_span("m") as chat:
            chat.record_usage(UsageSnapshot(input_tokens=1, output_tokens=1), stop_reason="end_turn")
            chat.record_completion("the answer is 42")

    names = _by_name(exporter.get_finished_spans())
    assert names["user_input"].attributes["gen_ai.prompt"] == "hello world"
    assert names["chat m"].attributes["gen_ai.completion"] == "the answer is 42"


def test_chat_span_records_system_provider(exporter):
    with spans.model_call_span("m", "openai") as chat:
        chat.record_usage(UsageSnapshot(input_tokens=1, output_tokens=1))
    attrs = _by_name(exporter.get_finished_spans())["chat m"].attributes
    assert attrs["gen_ai.system"] == "openai"


def test_chat_span_captures_tool_definitions(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    with spans.model_call_span("m") as chat:
        chat.record_request_tools('[{"name": "bash", "description": "run a command"}]')
    attrs = _by_name(exporter.get_finished_spans())["chat m"].attributes
    assert "bash" in attrs["gen_ai.request.tools"]


def test_tool_definitions_not_captured_when_gate_off(exporter, monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    with spans.model_call_span("m") as chat:
        chat.record_request_tools('[{"name": "bash"}]')
    attrs = _by_name(exporter.get_finished_spans())["chat m"].attributes
    assert "gen_ai.request.tools" not in attrs


def test_chat_span_captures_request_prompt(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    with spans.user_input_span(session_id="s", conversation_id="s", model="m", entrypoint="cli"):
        with spans.model_call_span("m") as chat:
            chat.record_prompt("[system]\nyou are x\n\n[user]\nhello there")
    attrs = _by_name(exporter.get_finished_spans())["chat m"].attributes
    assert "you are x" in attrs["gen_ai.prompt"]
    assert "hello there" in attrs["gen_ai.prompt"]


def test_capture_has_no_size_cap(exporter, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")
    big = "x" * 50000
    with spans.tool_span(tool_name="bash", tool_call_id="t", tool_input={"command": big}) as tool:
        tool.record_tool_result(big, is_error=False)

    attrs = _by_name(exporter.get_finished_spans())["execute_tool bash"].attributes
    assert len(attrs["openharness.tool.output"]) == 50000
    assert big in attrs["openharness.tool.input"]


def test_prompt_not_captured_when_gate_off(exporter, monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    with spans.user_input_span(
        session_id="s", conversation_id="s", model="m", entrypoint="cli", prompt="secret prompt"
    ):
        pass
    attrs = _by_name(exporter.get_finished_spans())["user_input"].attributes
    assert "gen_ai.prompt" not in attrs


def test_error_status_recorded(exporter):
    from opentelemetry.trace import StatusCode

    with pytest.raises(RuntimeError):
        with spans.model_call_span("m"):
            raise RuntimeError("boom")
    span = _by_name(exporter.get_finished_spans())["chat m"]
    assert span.status.status_code == StatusCode.ERROR


def test_noop_when_disabled():
    tracing.reset_tracing()
    # No provider installed -> helpers run without error and create no spans.
    with spans.user_input_span(session_id="s", conversation_id="s", model="m", entrypoint="cli"):
        with spans.model_call_span("m") as chat:
            chat.record_usage(UsageSnapshot(input_tokens=1, output_tokens=1), stop_reason="end_turn")
    assert tracing.get_tracer() is None
