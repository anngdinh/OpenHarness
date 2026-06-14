"""OpenTelemetry tracer setup — disabled unless an exporter is selected.

The OpenTelemetry packages are imported lazily inside ``init_tracing`` so that
importing this module (and ``openharness.observability``) never pulls in the SDK.
When no exporter is configured ``get_tracer()`` returns ``None`` and every span
helper degrades to a no-op.
"""
from __future__ import annotations

import os
from typing import Any

_initialized = False
_tracer: Any = None


def init_tracing() -> None:
    """Configure a global tracer provider from OTEL_* env vars (idempotent).

    Off unless ``OTEL_TRACES_EXPORTER`` is ``console`` or ``otlp``. Silently
    no-ops if the OpenTelemetry SDK (or OTLP exporter) is not installed.
    """
    global _initialized, _tracer
    if _initialized:
        return
    _initialized = True

    exporter_name = os.environ.get("OTEL_TRACES_EXPORTER", "none").strip().lower()
    if exporter_name in ("", "none"):
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        return

    if exporter_name == "console":
        exporter: Any = ConsoleSpanExporter()
    elif exporter_name == "otlp":
        exporter = _build_otlp_exporter()
        if exporter is None:
            return
    else:
        return

    try:
        from openharness import __version__ as version
    except Exception:
        version = "unknown"

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", "openharness"),
            "service.version": version,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = provider.get_tracer("openharness")


def _build_otlp_exporter() -> Any:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    except ImportError:
        pass
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter()
    except ImportError:
        return None


def get_tracer() -> Any:
    """Return the active tracer, or ``None`` when tracing is disabled."""
    return _tracer


def is_enabled() -> bool:
    """Whether tracing is active."""
    return _tracer is not None


def use_tracer_provider(provider: Any) -> None:
    """Test hook: install a tracer provider (e.g. with an in-memory exporter)."""
    global _initialized, _tracer
    _initialized = True
    _tracer = provider.get_tracer("openharness")


def reset_tracing() -> None:
    """Test hook: disable tracing again."""
    global _initialized, _tracer
    _initialized = False
    _tracer = None
