"""Reuse the A2A fake streaming client for domo tests."""

import pytest

from tests.test_a2a.conftest import FakeStreamingClient


@pytest.fixture
def fake_client_factory():
    def make(turns):
        return FakeStreamingClient(turns)
    return make


@pytest.fixture(autouse=True)
def _reset_coordinator_mode(monkeypatch):
    """domo tests build real engines/system prompts; ensure ambient coordinator-mode
    env leakage from other test suites does not flip the system prompt."""
    monkeypatch.delenv("CLAUDE_CODE_COORDINATOR_MODE", raising=False)
