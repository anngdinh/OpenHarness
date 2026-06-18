"""Chat model factory (OpenAI-compatible)."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from lgharness.config.settings import Settings
from lgharness.tools import DEFAULT_TOOLS


def build_model(settings: Settings):
    """Return a tools-bound OpenAI-compatible chat model."""
    model = ChatOpenAI(
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        temperature=0,
    )
    return model.bind_tools(DEFAULT_TOOLS)
