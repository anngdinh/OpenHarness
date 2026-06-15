"""Tests for the observability facade: disabled/no-op behavior."""
from __future__ import annotations

import subprocess
import sys

import pytest


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing()
    assert tracing.is_enabled() is False
    assert tracing.get_tracer() is None


def test_none_exporter_stays_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing()
    assert tracing.is_enabled() is False


def test_observability_settings_defaults():
    from openharness.config.settings import ObservabilitySettings

    s = ObservabilitySettings()
    assert s.exporter == "none"
    assert s.capture_content is False
    assert s.service_name == "openharness"
    assert s.otlp_endpoint is None


def test_settings_console_enables_tracing(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    from openharness.config.settings import ObservabilitySettings
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing(ObservabilitySettings(exporter="console"))
    try:
        assert tracing.is_enabled() is True
    finally:
        tracing.reset_tracing()


def test_env_exporter_overrides_settings(monkeypatch):
    # Explicit env "none" must win over a settings request to enable.
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "none")
    from openharness.config.settings import ObservabilitySettings
    from openharness.observability import tracing

    tracing.reset_tracing()
    tracing.init_tracing(ObservabilitySettings(exporter="console"))
    try:
        assert tracing.is_enabled() is False
    finally:
        tracing.reset_tracing()


def test_capture_content_from_settings(monkeypatch):
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    from openharness.config.settings import ObservabilitySettings
    from openharness.observability import spans, tracing

    tracing.reset_tracing()
    tracing.init_tracing(ObservabilitySettings(exporter="console", capture_content=True))
    try:
        assert spans.capture_content_enabled() is True
    finally:
        tracing.reset_tracing()


def test_observability_settings_otlp_headers_default():
    from openharness.config.settings import ObservabilitySettings

    assert ObservabilitySettings().otlp_headers == {}


def test_parse_headers_handles_base64_padding():
    from openharness.observability import tracing

    parsed = tracing._parse_headers("Authorization=Basic YWxhZGRpbjpvcGVu==,X-Scope-OrgID=tenant1")
    assert parsed == {"Authorization": "Basic YWxhZGRpbjpvcGVu==", "X-Scope-OrgID": "tenant1"}


def test_resolve_headers_from_settings(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADERS", raising=False)
    from openharness.config.settings import ObservabilitySettings
    from openharness.observability import tracing

    cfg = ObservabilitySettings(otlp_headers={"Authorization": "Basic SET"})
    assert tracing._resolve_headers(cfg) == {"Authorization": "Basic SET"}


def test_resolve_headers_env_overrides_settings(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=Basic ENVVAL")
    from openharness.config.settings import ObservabilitySettings
    from openharness.observability import tracing

    cfg = ObservabilitySettings(otlp_headers={"Authorization": "Basic SETTINGSVAL"})
    assert tracing._resolve_headers(cfg) == {"Authorization": "Basic ENVVAL"}


def test_build_otlp_exporter_carries_endpoint_and_headers():
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    from openharness.observability import tracing

    exp = tracing._build_otlp_exporter(
        "https://jaeger-4318.example/v1/traces",
        {"Authorization": "Basic Zm9vOmJhcg=="},
    )
    assert exp is not None
    assert exp._endpoint == "https://jaeger-4318.example/v1/traces"
    assert exp._session.headers.get("Authorization") == "Basic Zm9vOmJhcg=="


def test_settings_json_roundtrip_enables_tracing(tmp_path, monkeypatch):
    # The exact CLI path: load_settings(<settings.json>).observability -> init_tracing.
    monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
    import json

    from openharness.config.settings import load_settings
    from openharness.observability import tracing

    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"observability": {"exporter": "console", "capture_content": True}}),
        encoding="utf-8",
    )
    loaded = load_settings(config)
    assert loaded.observability.exporter == "console"

    tracing.reset_tracing()
    tracing.init_tracing(loaded.observability)
    try:
        assert tracing.is_enabled() is True
        assert tracing.capture_content_enabled() is True
    finally:
        tracing.reset_tracing()


def test_importing_facade_does_not_import_opentelemetry():
    # Run in a clean subprocess so other tests' imports don't pollute sys.modules.
    code = (
        "import sys; import openharness.observability as obs; "
        "obs.init_tracing(); "
        "assert 'opentelemetry' not in sys.modules, sorted(m for m in sys.modules if 'opentel' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
