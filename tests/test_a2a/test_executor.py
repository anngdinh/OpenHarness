import pytest

from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent

from openharness.a2a.executor import HarnessAgentExecutor
from openharness.a2a.sessions import SessionManager


class CapturingQueue:
    """Stands in for a2a EventQueue: records enqueued events."""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def enqueue_event(self, event: object) -> None:
        self.events.append(event)


class FakeRequestContext:
    def __init__(self, text: str, task_id: str, context_id: str) -> None:
        self._text = text
        self.task_id = task_id
        self.context_id = context_id
        self.current_task = None

    def get_user_input(self) -> str:
        return self._text


@pytest.mark.asyncio
async def test_execute_streams_and_completes(tmp_path, fake_client_factory):
    mgr = SessionManager(cwd=str(tmp_path), api_client=fake_client_factory([["Hello ", "world"]]))
    ex = HarnessAgentExecutor(mgr)
    q = CapturingQueue()
    ctx = FakeRequestContext("hi", task_id="t1", context_id="c1")

    await ex.execute(ctx, q)

    assert q.events, "expected events to be enqueued"
    assert any(isinstance(e, TaskArtifactUpdateEvent) for e in q.events), "expected a final artifact"
    assert any(isinstance(e, TaskStatusUpdateEvent) for e in q.events), "expected status updates"
