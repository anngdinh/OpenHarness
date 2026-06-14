"""Per-contextId session manager for the A2A server."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from openharness.api.client import SupportsStreamingMessages
from openharness.engine.query_engine import QueryEngine
from openharness.ui.runtime import build_runtime


@dataclass
class A2ASession:
    """One A2A conversation (contextId) bound to a QueryEngine."""

    context_id: str
    engine: QueryEngine
    # asyncio.Future the agent's ask_user_prompt awaits while input-required.
    pending_input: asyncio.Future[str] | None = field(default=None)


class SessionManager:
    """Owns QueryEngine instances keyed by A2A contextId (one agent config)."""

    def __init__(
        self,
        *,
        cwd: str,
        api_client: SupportsStreamingMessages | None = None,
        model: str | None = None,
        permission_mode: str | None = None,
        build_engine: Callable[[str], Awaitable[QueryEngine]] | None = None,
    ) -> None:
        self._cwd = cwd
        self._api_client = api_client
        self._model = model
        self._permission_mode = permission_mode
        self._build_engine = build_engine
        self._sessions: dict[str, A2ASession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, context_id: str) -> A2ASession:
        async with self._lock:
            existing = self._sessions.get(context_id)
            if existing is not None:
                return existing
            if self._build_engine is not None:
                engine = await self._build_engine(context_id)
            else:
                bundle = await build_runtime(
                    cwd=self._cwd,
                    model=self._model,
                    permission_mode=self._permission_mode,
                    api_client=self._api_client,
                    enforce_max_turns=True,
                )
                engine = bundle.engine
            session = A2ASession(context_id=context_id, engine=engine)
            self._sessions[context_id] = session
            return session

    def get(self, context_id: str) -> A2ASession | None:
        return self._sessions.get(context_id)
