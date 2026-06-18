import os
import pytest
from lgharness.config.settings import Settings
from lgharness.permissions.modes import PermissionMode


def test_defaults():
    s = Settings(base_url="http://x/v1", api_key="k")
    assert s.model == "gpt-4o-mini"
    assert s.permission_mode == PermissionMode.DEFAULT
    assert s.max_turns == 25


def test_from_env_reads_and_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "envkey")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env/v1")
    s = Settings.from_env(model="gpt-test")
    assert s.api_key == "envkey"
    assert s.base_url == "http://env/v1"
    assert s.model == "gpt-test"


def test_permission_mode_coerces_from_string():
    s = Settings(base_url="b", api_key="k", permission_mode="full_auto")
    assert s.permission_mode is PermissionMode.FULL_AUTO
