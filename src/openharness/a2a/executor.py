"""A2A AgentExecutor that drives the OpenHarness QueryEngine."""

from __future__ import annotations

import logging
import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState

from openharness.a2a.events import ArtifactChunk, Failure, StatusUpdate, Usage, map_stream_event
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

        # Stream the answer as artifact-update chunks (kind=artifact-update) so a
        # client can render it live and tell it apart from progress. Tool/status
        # events go out as status-update (kind=status-update) with metadata. One
        # chunk is held back so the final one can carry last_chunk=True.
        artifact_id = uuid.uuid4().hex
        pending: str | None = None
        started = False  # the artifact has been created (first chunk: append=False)
        input_tokens = 0
        output_tokens = 0
        try:
            async for event in session.engine.submit_message(prompt):
                intent = map_stream_event(event)
                if isinstance(intent, ArtifactChunk):
                    if pending is not None:
                        await updater.add_artifact(
                            [Part(text=pending)],
                            artifact_id=artifact_id,
                            name=_ARTIFACT_NAME,
                            append=started,
                            last_chunk=False,
                        )
                        started = True
                    pending = intent.text
                elif isinstance(intent, StatusUpdate):
                    await updater.update_status(
                        TaskState.TASK_STATE_WORKING,
                        message=updater.new_agent_message(
                            [Part(text=intent.text)], metadata=intent.metadata or None
                        ),
                    )
                elif isinstance(intent, Usage):
                    input_tokens += intent.input_tokens
                    output_tokens += intent.output_tokens
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

        # A2A has no first-class usage field; surface the total via the artifact's
        # metadata (A2A's sanctioned extension carrier). Omitted when unavailable.
        metadata = None
        if input_tokens or output_tokens:
            metadata = {
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            }

        # Flush the final answer chunk, marking the artifact stream complete.
        if pending is not None:
            await updater.add_artifact(
                [Part(text=pending)],
                artifact_id=artifact_id,
                name=_ARTIFACT_NAME,
                metadata=metadata,
                append=started,
                last_chunk=True,
            )
        elif not started:
            # No assistant text at all — still emit one (empty) artifact so a
            # blocking message/send returns a well-formed result.
            await updater.add_artifact(
                [Part(text="")],
                artifact_id=artifact_id,
                name=_ARTIFACT_NAME,
                metadata=metadata,
                last_chunk=True,
            )
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
