"""Shared test doubles for A2A tests."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from openharness.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiTextDeltaEvent,
)
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock


class FakeStreamingClient:
    """A SupportsStreamingMessages that replays scripted turns.

    Each scripted turn is a list of text chunks; the turn yields those as
    ApiTextDeltaEvents then a final assistant message with no tool calls,
    which makes run_query stop after the turn.
    """

    def __init__(self, turns: list[list[str]]) -> None:
        self._turns = list(turns)
        self.calls = 0

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[object]:
        chunks = self._turns[self.calls] if self.calls < len(self._turns) else ["(done)"]
        self.calls += 1
        text = ""
        for chunk in chunks:
            text += chunk
            yield ApiTextDeltaEvent(text=chunk)
        message = ConversationMessage(role="assistant", content=[TextBlock(text=text)])
        yield ApiMessageCompleteEvent(message=message, usage=UsageSnapshot())


@pytest.fixture
def fake_client_factory():
    def make(turns: list[list[str]]) -> FakeStreamingClient:
        return FakeStreamingClient(turns)
    return make
