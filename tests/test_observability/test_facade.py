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
