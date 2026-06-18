"""Harness configuration."""

from __future__ import annotations

import os

from pydantic import BaseModel

from lgharness.permissions.modes import PermissionMode


class Settings(BaseModel):
    """Runtime configuration for a harness session."""

    base_url: str
    api_key: str
    model: str = "gpt-4o-mini"
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    max_turns: int = 25

    @classmethod
    def from_env(cls, **overrides: object) -> "Settings":
        """Build settings from OPENAI_* env vars, with explicit overrides."""
        values: dict[str, object] = {
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key": os.environ.get("OPENAI_API_KEY", ""),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
