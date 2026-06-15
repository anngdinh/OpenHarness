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
_capture_content = False


def _env(name: str) -> str | None:
    """Return a non-empty env var value, else None."""
    value = os.environ.get(name)
    if value is not None and value.strip() != "":
        return value.strip()
    return None


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "on")


def init_tracing(config: Any = None) -> None:
    """Configure a global tracer provider (idempotent).

    Reads config from ``OTEL_*`` env vars, falling back to ``config`` (a
    ``Settings.observability`` object with ``exporter`` / ``otlp_endpoint`` /
    ``service_name`` / ``capture_content``). Env vars take precedence so
    settings.json works standalone while env still overrides.

    Off unless the resolved exporter is ``console`` or ``otlp``. Silently
    no-ops if the OpenTelemetry SDK (or OTLP exporter) is not installed.
    """
    global _initialized, _tracer, _capture_content
    if _initialized:
        return
    _initialized = True

    def cfg(attr: str, default: Any) -> Any:
        return getattr(config, attr, default) if config is not None else default

    # Content capture: env wins over settings.
    env_capture = _env("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")
    _capture_content = _is_truthy(env_capture) if env_capture is not None else bool(cfg("capture_content", False))

    # Exporter selection: env wins over settings.
    exporter_name = (_env("OTEL_TRACES_EXPORTER") or str(cfg("exporter", "none"))).strip().lower()
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
        endpoint = _env("OTEL_EXPORTER_OTLP_ENDPOINT") or cfg("otlp_endpoint", None)
        exporter = _build_otlp_exporter(endpoint)
        if exporter is None:
            return
    else:
        return

    import importlib.metadata

    try:
        version = importlib.metadata.version("openharness")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    service_name = _env("OTEL_SERVICE_NAME") or str(cfg("service_name", "openharness")) or "openharness"
    resource = Resource.create({"service.name": service_name, "service.version": version})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = provider.get_tracer("openharness")


def _build_otlp_exporter(endpoint: str | None = None) -> Any:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpExporter,
        )

        return HttpExporter(endpoint=endpoint) if endpoint else HttpExporter()
    except ImportError:
        pass
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcExporter,
        )

        return GrpcExporter(endpoint=endpoint) if endpoint else GrpcExporter()
    except ImportError:
        return None


def capture_content_enabled() -> bool:
    """Whether prompt / tool payloads may be attached to spans (env wins)."""
    env_capture = _env("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")
    if env_capture is not None:
        return _is_truthy(env_capture)
    return _capture_content


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
    global _initialized, _tracer, _capture_content
    _initialized = False
    _tracer = None
    _capture_content = False
