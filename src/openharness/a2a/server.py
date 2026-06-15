"""Assemble and run the A2A server (a2a-sdk 1.1.0)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from a2a.server.events import InMemoryQueueManager
from a2a.server.request_handlers import LegacyRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.utils import DEFAULT_RPC_URL
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from openharness.a2a.card import build_agent_card
from openharness.a2a.config import A2AServerSettings
from openharness.a2a.executor import HarnessAgentExecutor
from openharness.a2a.sessions import SessionManager


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a matching bearer token (well-known path is open)."""

    def __init__(self, app, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/.well-known"):
            return await call_next(request)
        if request.headers.get("authorization", "") != f"Bearer {self._token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_asgi_app(
    *,
    a2a_settings: A2AServerSettings,
    cwd: str,
    api_client=None,
    model: str | None = None,
    permission_mode: str | None = None,
    build_engine=None,
) -> Starlette:
    """Build the Starlette ASGI app (used by tests and by `oh a2a-serve`)."""
    card = build_agent_card(a2a_settings)
    sessions = SessionManager(
        cwd=cwd, api_client=api_client, model=model, permission_mode=permission_mode,
        build_engine=build_engine,
    )
    push_store = InMemoryPushNotificationConfigStore()
    push_client = httpx.AsyncClient()
    push_sender = BasePushNotificationSender(
        httpx_client=push_client, config_store=push_store
    )
    handler = LegacyRequestHandler(
        agent_executor=HarnessAgentExecutor(sessions),
        task_store=InMemoryTaskStore(),
        agent_card=card,
        queue_manager=InMemoryQueueManager(),
        push_config_store=push_store,
        push_sender=push_sender,
    )
    routes = (
        create_agent_card_routes(card)
        # Legacy A2A well-known path (older clients fetch /.well-known/agent.json
        # instead of the 1.x /.well-known/agent-card.json). Same card, same JSON.
        + create_agent_card_routes(card, card_url="/.well-known/agent.json")
        + create_jsonrpc_routes(handler, DEFAULT_RPC_URL, enable_v0_3_compat=True)
    )

    @asynccontextmanager
    async def _lifespan(app):
        try:
            yield
        finally:
            await push_client.aclose()

    app = Starlette(routes=routes, lifespan=_lifespan)
    if a2a_settings.auth_token:
        app.add_middleware(_BearerAuthMiddleware, token=a2a_settings.auth_token)
    return app


def run_a2a_server(
    *,
    a2a_settings: A2AServerSettings,
    cwd: str,
    model: str | None = None,
    permission_mode: str | None = None,
    build_engine=None,
) -> None:
    """Run the server with uvicorn (blocking)."""
    import uvicorn

    from openharness import observability as obs
    from openharness.config.settings import load_settings

    obs.init_tracing(load_settings().observability)

    app = build_asgi_app(
        a2a_settings=a2a_settings, cwd=cwd, model=model, permission_mode=permission_mode,
        build_engine=build_engine,
    )
    uvicorn.run(app, host=a2a_settings.host, port=a2a_settings.port)
