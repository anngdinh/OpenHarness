"""Build the A2A Agent Card from OpenHarness settings (a2a-sdk 1.1.0)."""

from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityScheme,
)
from a2a.utils import DEFAULT_RPC_URL, TransportProtocol

from openharness.a2a.config import A2AServerSettings


def build_agent_card(a2a_settings: A2AServerSettings) -> AgentCard:
    """Return the A2A Agent Card (a2a-sdk 1.1.0 protobuf message)."""
    rpc_url = a2a_settings.public_url.rstrip("/") + DEFAULT_RPC_URL
    kwargs: dict = dict(
        name=a2a_settings.agent_name,
        description=a2a_settings.agent_description,
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(protocol_binding=TransportProtocol.JSONRPC, url=rpc_url)
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="harness",
                name="OpenHarness agent",
                description="General-purpose coding/automation agent running on OpenHarness.",
                tags=["coding", "automation", "general"],
                examples=["Summarize the repo", "Fix the failing test in module X"],
            )
        ],
    )
    if a2a_settings.auth_token:
        kwargs["security_schemes"] = {
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer")
            )
        }
    return AgentCard(**kwargs)
