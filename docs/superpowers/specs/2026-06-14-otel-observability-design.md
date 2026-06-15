# OpenTelemetry tracing for the agent loop

**Date:** 2026-06-14
**Status:** Approved — ready for implementation planning
**Branch:** `feat/otel-observability`

## Goal

Add **observability for debugging interactive/dev sessions**: let a developer see
exactly what the agent did for a given prompt — the turn → model call → tool call
loop, with timings, token usage, and errors — as an OpenTelemetry trace tree.

Delivery is **OpenTelemetry spans** (vendor-agnostic), exported to a console
exporter or an OTLP backend (Jaeger/Tempo/collector), selected via the standard
`OTEL_*` environment variables. **Off by default** — normal users are unaffected.

This is not production metrics/monitoring (Prometheus/Grafana), and not a custom
trace-file format. Those were considered and rejected for this goal.

## Architecture

A new self-contained package `src/openharness/observability/` owns *all* OTel
concerns behind a thin facade. The engine calls the facade; the facade is a cheap
**no-op** unless OTel is installed *and* an exporter is selected. OTel knowledge
stays out of the hot loop, and the feature is inert by default.

```
src/openharness/observability/
  __init__.py    # public facade: init_tracing(), the span helpers, is_enabled()
  tracing.py     # idempotent provider+exporter setup from env (OTEL_* vars)
  spans.py       # span context-managers, semconv attribute setters, content gate
```

Integration approach (chosen over an event-listener and a hybrid): instrument the
engine directly at the real boundaries via the no-op facade. This is the only
approach that yields an accurate, complete span tree with correct token
attribution, and it covers every entrypoint (CLI / A2A / channels / domo) because
they all funnel through `QueryEngine`.

## Span model (the trace tree)

One trace per **user input**. Parent → child:

```
user_input            (QueryEngine.submit_message / continue_pending)
└─ turn               (each while-iteration in run_query)
   ├─ chat {model}    (api_client.stream_message block)
   └─ execute_tool {name}  (each _execute_tool_call — single & concurrent paths)
```

Span boundaries in code:

| Span          | Location                                                       |
|---------------|---------------------------------------------------------------|
| `user_input`  | `QueryEngine.submit_message` / `continue_pending`             |
| `turn`        | each `while` iteration in `run_query` (`query.py:700`)         |
| `chat {model}`| the `api_client.stream_message(...)` block (`query.py:727-752`)|
| `execute_tool`| wrapping `_execute_tool_call` (`query.py:887`)                 |

Attributes follow OTel **GenAI semantic conventions** where they fit, plus
`openharness.*` for the rest:

- **user_input**: `openharness.session.id`, `openharness.conversation.id`,
  `gen_ai.request.model`, `openharness.entrypoint`
- **turn**: `openharness.turn.index`
- **chat**: `gen_ai.operation.name=chat`, `gen_ai.system`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.response.finish_reasons`; records exceptions + sets span status ERROR on
  API failure
- **execute_tool**: `gen_ai.tool.name`, `gen_ai.tool.call.id`,
  `openharness.tool.is_error`, `openharness.tool.output.length`

## Parent propagation

`run_query` is an **async generator that yields mid-turn** and runs tools
**concurrently** via `asyncio.gather`. Ambient "current span" (contextvar) is
unreliable across `yield` and across tasks. So span parenting uses **explicit
context** (`trace.set_span_in_context(parent)`) rather than ambient current-span.
This guarantees a correct tree even with concurrent tools and generator
suspension — and is verified by tests.

## Config

Configurable two ways, with **env vars taking precedence over `settings.json`**
(so settings.json works standalone while env still overrides per-run). The
`Settings.observability` section mirrors the env vars:

```jsonc
"observability": {
  "exporter": "none",            // "none" (default) | "console" | "otlp"
  "otlp_endpoint": null,         // full signal URL, e.g. https://host/v1/traces
  "otlp_headers": {},            // custom headers (e.g. Authorization for a gateway)
  "service_name": "openharness",
  "capture_content": false
}
```

`init_tracing()` is called at CLI startup with `load_settings().observability`.

### Standard OTel env vars

- `OTEL_TRACES_EXPORTER` = `none` (default) | `console` | `otlp` — **off unless set**
- `OTEL_EXPORTER_OTLP_ENDPOINT` — for `otlp` (Jaeger/Tempo/collector)
- `OTEL_SERVICE_NAME` — defaults to `openharness`
- `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` = `true` — the **payload
  gate**; when on, the user prompt (`gen_ai.prompt` on `user_input`), the
  assistant reply (`gen_ai.completion` on `chat`), and tool input/output are
  attached to spans **untruncated**. Off by default. The gate is enforced in one
  place (`spans.py`): call sites always pass payloads and the helper decides
  whether to attach them.

## Dependency strategy (zero impact by default)

No new **mandatory** deps. The facade guards its OTel import
(`try/except ImportError` → no-op). A new optional extra in `pyproject.toml`:

```toml
observability = ["opentelemetry-sdk>=1.20", "opentelemetry-exporter-otlp>=1.20"]
```

- `pip install openharness-ai` → unchanged.
- `pip install openharness-ai[observability]` + `OTEL_TRACES_EXPORTER=otlp` → on.

## Initialization

`init_tracing()` is idempotent and reads env once. **v1 wires it into CLI
startup** (the dev/interactive surface — the stated goal), next to the existing
`logging.basicConfig` in `cli.py`. Because the root span lives in the shared
`QueryEngine`, A2A / domo / channels get tracing for free by adding the same
one-line `init_tracing()` call — listed as a trivial optional follow-up, not v1.

## Safety

Telemetry must never break a turn: all facade helpers swallow OTel-internal
errors. Program exceptions inside a span are recorded (status ERROR) and
**re-raised unchanged** — the loop's existing error handling is untouched.

## Test plan (`InMemorySpanExporter`)

1. **Disabled** → helpers run, produce no spans, and do not import the SDK.
2. **Full loop** (fake `api_client`: a tool_use turn → a final-text turn) →
   asserts the `user_input → turn → {chat, execute_tool}` tree plus a 2nd turn.
3. **Attributes** present and correct (model, token counts, finish reason, tool
   name / is_error).
4. **Content gate**: off → no payload attributes; on → payloads attached.
5. **API error** → `chat` span status ERROR + recorded exception; loop still
   yields `ErrorEvent`.
6. **Concurrent tools**: two tool_uses → two `execute_tool` spans, both children
   of the same `turn` span.

## Non-goals (v1)

- Production metrics / Prometheus / Grafana
- Compaction / subagent / MCP spans
- Cross-process trace propagation into spawned subagents
- Log ↔ trace correlation

All deferred; the facade and span model leave room to add them later.
