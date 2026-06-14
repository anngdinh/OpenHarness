import json

import httpx
import pytest

from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH, DEFAULT_RPC_URL

from openharness.a2a.config import A2AServerSettings
from openharness.a2a.server import build_asgi_app


@pytest.mark.asyncio
async def test_agent_card_served(tmp_path, fake_client_factory):
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["hi"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
    assert resp.status_code == 200
    assert resp.json()["skills"][0]["id"] == "harness"


@pytest.mark.asyncio
async def test_legacy_well_known_agent_json_alias(tmp_path, fake_client_factory):
    """Older A2A clients fetch /.well-known/agent.json; serve the same card there."""
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["hi"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        modern = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
        legacy = await client.get("/.well-known/agent.json")
    assert modern.status_code == 200
    assert legacy.status_code == 200
    assert legacy.json() == modern.json()


@pytest.mark.asyncio
async def test_auth_required_when_token_set(tmp_path, fake_client_factory):
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(auth_token="secret"),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["hi"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            DEFAULT_RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_correct_token_passes(tmp_path, fake_client_factory):
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(auth_token="secret"),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["hi"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            DEFAULT_RPC_URL,
            headers={"Authorization": "Bearer secret"},
            json={"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}},
        )
    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_well_known_open_when_auth_enabled(tmp_path, fake_client_factory):
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(auth_token="secret"),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["hi"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
    assert resp.status_code == 200


class _RaisingClient:
    """A streaming client that raises mid-stream to exercise the error path."""

    async def stream_message(self, request):  # noqa: ANN001
        raise RuntimeError("boom provider error")
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.asyncio
async def test_message_send_engine_error_yields_failed_task(tmp_path):
    """Engine error must produce a FAILED task, not a transport-level crash.

    Regression: the executor previously called update_status(..., final=True),
    but a2a-sdk's TaskUpdater.update_status has no `final` kwarg, so the error
    path raised TypeError -> JSON-RPC -32603 instead of a clean FAILED status.
    """
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(),
        cwd=str(tmp_path),
        api_client=_RaisingClient(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            DEFAULT_RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "ping"}],
                    }
                },
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    # The bug surfaced as a JSON-RPC error mentioning the bad 'final' kwarg.
    assert "error" not in body, body
    status = body["result"]["status"]
    assert "fail" in str(status["state"]).lower(), status


@pytest.mark.asyncio
async def test_message_send_end_to_end(tmp_path, fake_client_factory):
    """Drive the REAL request handler via JSON-RPC message/send (not a fake queue)."""
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["Pong"]]),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            DEFAULT_RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "m1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "ping"}],
                    }
                },
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" not in body, body
    artifacts = body["result"]["artifacts"]
    texts = "".join(p.get("text", "") for a in artifacts for p in a["parts"])
    assert "Pong" in texts


@pytest.mark.asyncio
async def test_message_stream_answer_arrives_as_artifact_updates(tmp_path, fake_client_factory):
    """The streamed answer must arrive as artifact-update events (not status).

    Tokens map to kind=artifact-update so a client can render the live answer and
    distinguish it from status-update progress (tool/system messages).
    """
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(),
        cwd=str(tmp_path),
        api_client=fake_client_factory([["Hello", " ", "World"]]),
    )
    transport = httpx.ASGITransport(app=app)
    kinds: list[str] = []
    artifact_text = ""
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            DEFAULT_RPC_URL,
            headers={"Accept": "text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/stream",
                "params": {
                    "message": {
                        "messageId": "m1",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "hi"}],
                    }
                },
            },
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                result = event.get("result", event)
                kind = result.get("kind")
                if kind:
                    kinds.append(kind)
                if kind == "artifact-update":
                    artifact = result.get("artifact") or {}
                    artifact_text += "".join(p.get("text", "") for p in artifact.get("parts", []))
    # The answer came through as artifact-update events and reassembles in order.
    assert "artifact-update" in kinds, kinds
    assert artifact_text == "Hello World", artifact_text
