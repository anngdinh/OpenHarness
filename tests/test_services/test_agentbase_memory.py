"""Tests for the AgentBase memory backend wrapper (no live creds needed)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("greennode_agentbase")

from openharness.config.settings import AgentBaseMemoryConfig, MemorySettings
from openharness.services import agentbase_memory as am

CFG = AgentBaseMemoryConfig(memory_id="mem-1", strategy_id="strat-1")


class FakeClient:
    def __init__(self) -> None:
        self.events: list = []
        self.generated = None
        self.searched = None
        self.closed = False

    async def create_event_async(self, *, id, actorId, sessionId, request):  # noqa: A002,N803
        self.events.append((actorId, sessionId, request.payload.role, request.payload.message))

    async def list_events_async(self, *, id, actorId, sessionId, page, size):  # noqa: A002,N803
        # Returned newest-first on purpose to prove the wrapper sorts chronologically.
        newer = SimpleNamespace(
            payload=SimpleNamespace(role="assistant", message="second"),
            event_timestamp="2026-01-01T00:00:02Z",
        )
        older = SimpleNamespace(
            payload=SimpleNamespace(role="user", message="first"),
            event_timestamp="2026-01-01T00:00:01Z",
        )
        return SimpleNamespace(list_data=[newer, older])

    async def search_memory_records_async(self, *, id, namespace, request):  # noqa: A002
        self.searched = (namespace, request.query)
        return SimpleNamespace(list_data=[SimpleNamespace(memory="user likes iced coffee", score=0.9)])

    async def generate_memory_records_from_session_async(self, *, id, actorId, sessionId, longTermMemoryStrategyId):  # noqa: A002,N803
        self.generated = (id, actorId, sessionId, longTermMemoryStrategyId)

    async def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(am, "_client", lambda config: client)
    return client


@pytest.mark.asyncio
async def test_write_turns_skips_empty(fake):
    await am.write_turns(CFG, "alice", "alice", [("user", "hi"), ("assistant", "   "), ("user", "there")])
    assert [(role, msg) for (_, _, role, msg) in fake.events] == [("user", "hi"), ("user", "there")]
    assert fake.closed


@pytest.mark.asyncio
async def test_recent_conversation_text_is_chronological(fake):
    text = await am.recent_conversation_text(CFG, "alice", "alice")
    assert text == "- user: first\n- assistant: second"


@pytest.mark.asyncio
async def test_search_facts_text(fake):
    text = await am.search_facts_text(CFG, "alice", "coffee?")
    assert text == "- user likes iced coffee"
    assert fake.searched == ("/strategies/strat-1/actors/alice", "coffee?")


@pytest.mark.asyncio
async def test_search_facts_empty_query_is_noop(fake):
    assert await am.search_facts_text(CFG, "alice", "   ") == ""
    assert fake.searched is None


@pytest.mark.asyncio
async def test_generate_facts(fake):
    await am.generate_facts(CFG, "alice", "alice")
    assert fake.generated == ("mem-1", "alice", "alice", "strat-1")


def test_settings_backend_roundtrip():
    m = MemorySettings(backend="agentbase", agentbase=AgentBaseMemoryConfig(memory_id="x", strategy_id="y"))
    restored = MemorySettings.model_validate(m.model_dump())
    assert restored.backend == "agentbase"
    assert restored.agentbase.memory_id == "x"
    assert restored.agentbase.strategy_id == "y"
    # default stays "file"
    assert MemorySettings().backend == "file"
