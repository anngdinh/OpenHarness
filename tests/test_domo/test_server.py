import httpx
import pytest

from a2a.utils import AGENT_CARD_WELL_KNOWN_PATH, DEFAULT_RPC_URL

from openharness.a2a.config import A2AServerSettings
from openharness.a2a.server import build_asgi_app

from domo.agent import make_build_engine
from domo.config import DomoConfig


@pytest.mark.asyncio
async def test_card_and_message_via_domo_factory(tmp_path, fake_client_factory):
    config = DomoConfig(cwd=str(tmp_path))
    app = build_asgi_app(
        a2a_settings=A2AServerSettings(agent_name="domo"),
        cwd=str(tmp_path),
        build_engine=make_build_engine(config, api_client=fake_client_factory([["Pong"]])),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        card = await client.get(AGENT_CARD_WELL_KNOWN_PATH)
        assert card.status_code == 200
        assert card.json()["name"] == "domo"

        rpc = await client.post(
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
                        "contextId": "conv-1",
                    }
                },
            },
        )
        assert rpc.status_code == 200
        body = rpc.json()
        assert "error" not in body, body
        texts = "".join(p.get("text", "") for a in body["result"]["artifacts"] for p in a["parts"])
        assert "Pong" in texts
