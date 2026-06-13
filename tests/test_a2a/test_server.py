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
