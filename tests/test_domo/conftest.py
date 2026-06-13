"""Reuse the A2A fake streaming client for domo tests."""

import pytest

from tests.test_a2a.conftest import FakeStreamingClient


@pytest.fixture
def fake_client_factory():
    def make(turns):
        return FakeStreamingClient(turns)
    return make
