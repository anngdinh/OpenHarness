"""Configuration for the A2A server."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


class A2AServerSettings(BaseModel):
    """Runtime settings for `oh a2a-serve`."""

    host: str = "127.0.0.1"
    port: int = 9100
    public_url_override: str | None = Field(default=None, alias="public_url")
    auth_token: str | None = None
    agent_name: str = "OpenHarness Agent"
    agent_description: str = "An OpenHarness agent exposed over the A2A protocol."

    model_config = {"populate_by_name": True}

    @property
    def public_url(self) -> str:
        """Return the externally advertised base URL."""
        return self.public_url_override or f"http://{self.host}:{self.port}"

    @classmethod
    def from_env(cls) -> "A2AServerSettings":
        """Load settings from environment variables (secrets never baked)."""
        data: dict[str, object] = {}
        if host := os.environ.get("OPENHARNESS_A2A_HOST"):
            data["host"] = host
        if port := os.environ.get("OPENHARNESS_A2A_PORT"):
            data["port"] = int(port)
        if url := os.environ.get("OPENHARNESS_A2A_PUBLIC_URL"):
            data["public_url"] = url
        if token := os.environ.get("OPENHARNESS_A2A_AUTH_TOKEN"):
            data["auth_token"] = token
        return cls(**data)
