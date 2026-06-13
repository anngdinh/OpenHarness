"""Configuration for the domo domain-assistant agent."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from openharness.config.settings import PermissionSettings
from openharness.permissions.modes import PermissionMode

# Read-only kubectl is allowed; these mutating/dangerous patterns are denied.
KUBECTL_DENY_PATTERNS: list[str] = [
    # Mutating/dangerous kubectl verbs — matched anywhere in the command so
    # compound shells (e.g. "kubectl get x && kubectl delete y") are also caught.
    "*kubectl apply*",
    "*kubectl delete*",
    "*kubectl edit*",
    "*kubectl scale*",
    "*kubectl patch*",
    "*kubectl rollout*",
    "*kubectl drain*",
    "*kubectl cordon*",
    "*kubectl uncordon*",
    "*kubectl exec*",
    "*kubectl attach*",
    "*kubectl debug*",
    "*kubectl port-forward*",
    "*kubectl create*",
    "*kubectl replace*",
    "*kubectl cp*",
    "*kubectl set*",
    "*kubectl label*",
    "*kubectl annotate*",
    # Anchored (leading * would false-positive on words like "perform"):
    "rm *",
    "sudo *",
]


class DatasourceConfig(BaseModel):
    """One HTTP datasource MCP server."""

    name: str
    url: str
    token_env: str | None = None


class DomoConfig(BaseModel):
    """Runtime config for the domo agent."""

    model: str | None = None
    cwd: str = "."
    permission_mode: str = "full_auto"
    datasources: list[DatasourceConfig] = Field(default_factory=list)

    def permission_settings(self) -> PermissionSettings:
        """Read-mostly policy: allow everything except the kubectl/dangerous deny-list."""
        return PermissionSettings(
            mode=PermissionMode(self.permission_mode),
            denied_commands=list(KUBECTL_DENY_PATTERNS),
        )

    @classmethod
    def from_env(cls) -> "DomoConfig":
        """Load config from environment variables."""
        data: dict[str, object] = {}
        if model := os.environ.get("DOMO_MODEL"):
            data["model"] = model
        if cwd := os.environ.get("DOMO_CWD"):
            data["cwd"] = cwd
        if mode := os.environ.get("DOMO_PERMISSION_MODE"):
            data["permission_mode"] = mode
        return cls(**data)
