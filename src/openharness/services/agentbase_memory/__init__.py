"""AgentBase memory backend — thin wrapper over the greennode-agentbase SDK.

Optional: only used when ``settings.memory.backend == "agentbase"``. The SDK and
its IAM credentials (GREENNODE_CLIENT_ID/SECRET or .greennode.json) are required
only on that path, so imports are kept lazy.

Mapping (verified against greennode-agentbase 1.0.3):
- conversation continuity  -> Events  (create_event_async / list_events_async)
- durable facts            -> Memory Records (generate-from-session / search)
- contextId                -> actorId == sessionId (v1)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openharness.config.settings import AgentBaseMemoryConfig

log = logging.getLogger(__name__)


def _client(config: "AgentBaseMemoryConfig"):
    """Build a MemoryClient (reads IAM creds from env / .greennode.json)."""
    from greennode_agentbase.memory import MemoryClient

    return MemoryClient(base_url=config.base_url) if config.base_url else MemoryClient()


def _namespace(config: "AgentBaseMemoryConfig", actor: str) -> str:
    return f"/strategies/{config.strategy_id}/actors/{actor}"


async def write_turns(
    config: "AgentBaseMemoryConfig", actor: str, session: str, turns: list[tuple[str, str]]
) -> None:
    """Append conversation turns as events. ``turns`` is a list of (role, message)."""
    if not turns:
        return
    from greennode_agentbase.memory.models import EventCreateRequest, EventPayload

    client = _client(config)
    try:
        for role, message in turns:
            if not message.strip():
                continue
            await client.create_event_async(
                id=config.memory_id,
                actorId=actor,
                sessionId=session,
                request=EventCreateRequest(
                    payload=EventPayload(type="conversational", role=role, message=message)
                ),
            )
    finally:
        await client.close()


async def recent_conversation_text(
    config: "AgentBaseMemoryConfig", actor: str, session: str, limit: int = 20
) -> str:
    """Return recent events as chronological '- role: text' lines (oldest first)."""
    client = _client(config)
    try:
        result = await client.list_events_async(
            id=config.memory_id, actorId=actor, sessionId=session, page=1, size=limit
        )
    finally:
        await client.close()
    events = list(getattr(result, "list_data", []) or [])
    # Sort chronologically by timestamp — the API's default order is not reliable.
    events.sort(key=lambda e: getattr(e, "event_timestamp", "") or "")
    lines: list[str] = []
    for event in events:
        payload = getattr(event, "payload", None)
        role = getattr(payload, "role", None) or "?"
        message = (getattr(payload, "message", None) or "").strip()
        if message:
            lines.append(f"- {role}: {message}")
    return "\n".join(lines)


async def search_facts_text(
    config: "AgentBaseMemoryConfig", actor: str, query: str, limit: int = 10
) -> str:
    """Semantic-search durable memory records; return one fact per line."""
    if not query.strip():
        return ""
    from greennode_agentbase.memory.models import MemoryRecordSearchRequest

    client = _client(config)
    try:
        result = await client.search_memory_records_async(
            id=config.memory_id,
            namespace=_namespace(config, actor),
            request=MemoryRecordSearchRequest(query=query, limit=limit),
        )
    finally:
        await client.close()
    records = list(getattr(result, "list_data", result) or [])
    facts = [(getattr(r, "memory", None) or "").strip() for r in records]
    return "\n".join(f"- {fact}" for fact in facts if fact)


async def all_facts_text(config: "AgentBaseMemoryConfig", actor: str) -> str:
    """Browse all durable memory records for an actor; one fact per line."""
    client = _client(config)
    try:
        result = await client.list_memory_records_async(
            id=config.memory_id, namespace=_namespace(config, actor)
        )
    finally:
        await client.close()
    records = list(getattr(result, "list_data", result) or [])
    facts = [(getattr(r, "memory", None) or "").strip() for r in records]
    return "\n".join(f"- {fact}" for fact in facts if fact)


async def generate_facts(config: "AgentBaseMemoryConfig", actor: str, session: str) -> None:
    """Trigger long-term record generation from the session (async, best-effort)."""
    client = _client(config)
    try:
        await client.generate_memory_records_from_session_async(
            id=config.memory_id,
            actorId=actor,
            sessionId=session,
            longTermMemoryStrategyId=config.strategy_id,
        )
    finally:
        await client.close()
