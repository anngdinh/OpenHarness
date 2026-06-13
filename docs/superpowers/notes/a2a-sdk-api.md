# a2a-sdk 1.1.0 — verified API reference (Task 1 spike output)

**Pinned:** `a2a-sdk==1.1.0`, added as **optional extra** `a2a` in `pyproject.toml`
(`openharness-ai[a2a]`). Install for dev: `uv sync --extra a2a`.

**Dependency impact:** pulls `google-api-core`, `proto-plus`, and **protobuf 5 → 6**
(major bump). Verified non-breaking: `import openharness, lark_oapi, slack_sdk` all OK.

> ⚠️ **1.1.0 is a protobuf-native major rewrite.** It differs substantially from the
> 0.2.x API the plan's illustrative code targets. **This file is the source of truth.**
> Where a plan task's code conflicts, follow the verified patterns below.

## Key differences vs the plan's 0.2.x assumptions

| Plan assumed (0.2.x) | Reality (1.1.0) |
|---|---|
| `a2a.server.apps.A2AStarletteApplication` | **Does not exist.** Build routes + `Starlette` manually |
| pydantic types (`AgentCard(url=...)`) | **raw protobuf messages** (`a2a.types.*`), kwargs construction, proto field names |
| `AgentCard(url=...)` | no `url` field → use `supported_interfaces=[AgentInterface(protocol_binding=..., url=...)]` |
| custom `push.py` store | SDK provides `InMemoryPushNotificationConfigStore` + `PushNotificationSender` |
| `new_agent_text_message` helper | use `TaskUpdater.new_agent_message([Part(text=...)])`; text part = `Part(text=...)` |

## Verified imports

```python
from a2a.types import (
    AgentCard, AgentSkill, AgentCapabilities, AgentInterface, Part,
    SecurityScheme, HTTPAuthSecurityScheme, TaskState,
)
from a2a.utils import TransportProtocol, AGENT_CARD_WELL_KNOWN_PATH, DEFAULT_RPC_URL  # rpc default "/"
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    InMemoryTaskStore, TaskUpdater,
    InMemoryPushNotificationConfigStore, PushNotificationSender,
)
from a2a.server.events import InMemoryQueueManager
from a2a.server.routes import create_jsonrpc_routes, create_agent_card_routes
from starlette.applications import Starlette
```

## Proto field names (from DESCRIPTOR)

- **AgentCard**: `name, description, supported_interfaces, provider, version, documentation_url, capabilities, security_schemes, security_requirements, default_input_modes, default_output_modes, skills, signatures, icon_url` — **no `url`**.
- **AgentInterface**: `url, protocol_binding, tenant, protocol_version`. `protocol_binding=TransportProtocol.JSONRPC` (a string `"JSONRPC"`; also `GRPC`, `HTTP_JSON`).
- **AgentCapabilities**: `streaming, push_notifications, extensions, extended_agent_card`.
- **Part**: `text, raw, url, data, metadata, filename, media_type` → text part = `Part(text="...")`.
- **Message**: `message_id, context_id, task_id, role, parts, metadata, extensions, reference_task_ids`.
- **TaskState / Role**: protobuf enums (use `TaskState.<VALUE>`; inspect `.DESCRIPTOR` for value names during impl — e.g. for `update_status`).

## Key signatures

```
DefaultRequestHandler(agent_executor, task_store, agent_card,
    queue_manager=None, push_config_store=None, push_sender=None,
    request_context_builder=None, extended_agent_card=None, extended_card_modifier=None)

create_jsonrpc_routes(request_handler, rpc_url, context_builder=None, enable_v0_3_compat=False) -> list[Route]
create_agent_card_routes(agent_card, card_modifier=None, card_url='/.well-known/agent-card.json') -> list[Route]

RequestContext: .get_user_input(), .task_id, .context_id, .current_task, .message, .configuration, .metadata, .call_context
TaskUpdater(event_queue, task_id, context_id):
  .submit(), .start_work(), .update_status(state, message=None, final=False),
  .add_artifact(parts, artifact_id=None, name=None, metadata=None, append=None, last_chunk=None),
  .complete(), .failed(message=None), .cancel(), .reject(),
  .requires_input(message=None),   # ← INPUT-REQUIRED
  .requires_auth(...), .new_agent_message(parts, metadata=None) -> Message
AgentExecutor (abstract): async execute(context, event_queue); async cancel(context, event_queue)
```

## VERIFIED minimal server skeleton (ran green via httpx ASGITransport)

```python
import asyncio, httpx
from a2a.types import AgentCard, AgentSkill, AgentCapabilities, AgentInterface, Part
from a2a.utils import TransportProtocol, AGENT_CARD_WELL_KNOWN_PATH, DEFAULT_RPC_URL
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.server.events import InMemoryQueueManager
from a2a.server.routes import create_jsonrpc_routes, create_agent_card_routes
from starlette.applications import Starlette

card = AgentCard(
    name="OH", description="d", version="0.1.0",
    supported_interfaces=[AgentInterface(
        protocol_binding=TransportProtocol.JSONRPC, url="http://host" + DEFAULT_RPC_URL)],
    capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    default_input_modes=["text/plain"], default_output_modes=["text/plain"],
    skills=[AgentSkill(id="harness", name="n", description="d", tags=["x"])],
)

class Dummy(AgentExecutor):
    async def execute(self, context, event_queue):
        u = TaskUpdater(event_queue, context.task_id, context.context_id)
        await u.submit()
        await u.start_work()
        await u.add_artifact([Part(text="hi " + (context.get_user_input() or ""))], name="response")
        await u.complete()
    async def cancel(self, context, event_queue):
        pass

handler = DefaultRequestHandler(
    agent_executor=Dummy(), task_store=InMemoryTaskStore(),
    agent_card=card, queue_manager=InMemoryQueueManager(),
)
app = Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, DEFAULT_RPC_URL))
# GET AGENT_CARD_WELL_KNOWN_PATH -> 200, body.name == "OH", skills[0].id == "harness"
```

## Plan reconciliation (what changes)

- **Task 3 (card.py):** build protobuf `AgentCard` per skeleton above. Auth → `security_schemes`/`security_requirements` proto fields (inspect `SecurityScheme`/`HTTPAuthSecurityScheme` DESCRIPTOR during impl). No `url=` kwarg.
- **Task 7/11 (executor.py):** `Part(text=...)`, `updater.new_agent_message([...])`, `updater.update_status(...)`, `updater.add_artifact(...)`, `updater.requires_input(...)`, `updater.complete()/failed()`.
- **Task 8 (push.py):** prefer SDK `InMemoryPushNotificationConfigStore` + `PushNotificationSender` wired into `DefaultRequestHandler`. Custom store only if a gap appears.
- **Task 9 (server.py):** assemble with `create_agent_card_routes(card) + create_jsonrpc_routes(handler, DEFAULT_RPC_URL)` into `Starlette(routes=...)`; add bearer middleware. No `A2AStarletteApplication`.
- **Tasks 2,4,5,6 (config/events/fake-client/sessions):** unaffected — our code only.

## input-required routing — STILL TO CONFIRM in Task 11

Not yet verified: whether a follow-up `message/send` with the same `taskId` reaches `execute()` while the first run awaits, or invokes `execute()` again. `InMemoryQueueManager` + `updater.requires_input()` exist (the mechanism is present). Confirm behavior with a focused test at the start of Task 11 before wiring the suspend/resume.
