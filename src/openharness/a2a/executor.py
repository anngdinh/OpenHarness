"""A2A AgentExecutor that drives the OpenHarness QueryEngine."""

from __future__ import annotations

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState

from openharness.a2a.events import ArtifactChunk, Failure, StatusUpdate, map_stream_event
from openharness.a2a.sessions import SessionManager

log = logging.getLogger(__name__)

_ARTIFACT_NAME = "response"


class HarnessAgentExecutor(AgentExecutor):
    """Drive QueryEngine.submit_message and map its events to A2A events."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.submit()
        await updater.start_work()

        session = await self._sessions.get_or_create(context.context_id)
        prompt = context.get_user_input()

        buffer = ""
        try:
            async for event in session.engine.submit_message(prompt):
                intent = map_stream_event(event)
                if isinstance(intent, ArtifactChunk):
                    buffer += intent.text
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message([Part(text=intent.text)]),
                    )
                elif isinstance(intent, StatusUpdate):
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message([Part(text=intent.text)]),
                    )
                elif isinstance(intent, Failure):
                    await updater.failed(
                        message=updater.new_agent_message([Part(text=intent.text)]),
                    )
                    return
        except Exception as exc:
            log.exception("a2a execute failed task=%s", context.task_id)
            await updater.failed(
                message=updater.new_agent_message([Part(text=_sanitize(exc))]),
            )
            return

        await updater.add_artifact([Part(text=buffer)], name=_ARTIFACT_NAME)
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Real cancellation of an in-flight run is added in Task 11.
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


def _sanitize(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    lowered = msg.lower()
    if "api key" in lowered or "auth" in lowered or "credential" in lowered:
        return "Authentication failed for the agent's provider profile."
    return f"Agent error: {msg}"
