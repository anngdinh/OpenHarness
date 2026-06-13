# A2A Server cho OpenHarness — Design Spec

- **Ngày**: 2026-06-13
- **Branch**: `agentbase-harness`
- **Trạng thái**: Approved (chờ review spec) → tiếp theo: writing-plans

## 1. Mục tiêu

Thêm khả năng **A2A server** (Agent-to-Agent protocol, chuẩn mở của Google) vào **lõi OpenHarness** (`src/openharness/`), để các A2A client/agent bên ngoài gọi vào và điều khiển một agent chạy trên harness.

- Là **tính năng của core harness**, KHÔNG dính `ohmo`/persona/gateway.
- Chạy standalone qua CLI mới: `oh a2a-serve`.
- Dùng **a2a-sdk chính thức (Python)** làm vỏ giao thức; phần của ta là một **adapter mỏng** drive `QueryEngine` (Ports & Adapters).
- **Engine/loop (`engine/query.py`) không sửa một dòng.**

### Phạm vi v1 (full lifecycle)

- `message/send` và `message/stream` (SSE).
- `tasks/get`, `tasks/cancel`, `tasks/resubscribe`.
- `tasks/pushNotificationConfig/{set,get,list,delete}` + dispatch webhook.
- **input-required**: agent hỏi lại giữa task (qua tool `AskUserQuestion`) → client trả lời để tiếp tục.
- Streaming **hai dòng**: sự kiện tiến trình (tool/status) + kết quả cuối stream dần (artifact).
- Agent Card tại `/.well-known/agent-card.json`.
- Auth: bearer token đơn, tùy chọn.

### Non-goals (YAGNI — để sau)

- Multi-tenant: mỗi request một repo/cwd khác nhau. (v1: **một cwd chung**, quyết định 2a.)
- Worktree-isolation mỗi session (2b).
- Bọc `permission_prompt` thành input-required (3b) — v1 dùng policy phi-tương-tác (3a).
- File/Data parts phong phú — v1 chủ yếu `text/plain` (file artifact có thể thêm sau).
- Nhiều skill trong Agent Card — v1 đúng 1 skill tổng quát.

## 2. Quyết định đã chốt

| # | Quyết định | Chọn |
|---|---|---|
| Vai trò | server vs client | **Server (nhận vào)** |
| Substrate | ohmo gateway vs core | **Core harness, standalone** |
| Vỏ giao thức | a2a-sdk vs tự viết | **a2a-sdk (Hướng 1)** |
| Cấu hình | 1 agent 1 config | **Có**, nhưng **nhiều session độc lập** |
| cwd | chung vs worktree/session | **(2a) chung** |
| input-required | giữ hay bỏ | **Giữ** (qua `AskUserQuestion`) |
| permission trên server | policy vs round-trip | **(3a) policy phi-tương-tác**; (3b) sau |
| Streaming | event + kết quả cuối | **Giữ cả hai** |

## 3. Kiến trúc

```
  A2A client (CLI client của bạn / ADK / inspector...)
        │  HTTP + JSON-RPC 2.0 + SSE
        ▼
  ┌──────────────────────────────────────────────────────────┐
  │  src/openharness/a2a/   (MODULE MỚI, core)                 │
  │   server.py    A2AStarletteApplication + DefaultRequestHandler + uvicorn
  │   card.py      build AgentCard từ Settings + A2AServerSettings
  │   config.py    A2AServerSettings (host/port/url/auth/cwd/policy)
  │   sessions.py  SessionManager: contextId → QueryEngine
  │   executor.py  HarnessAgentExecutor(AgentExecutor)  ← ADAPTER duy nhất
  │   events.py    StreamEvent → A2A events (qua TaskUpdater)
  │   push.py      PushNotificationConfigStore + dispatcher (httpx)
  └─────────────────────────┬────────────────────────────────┘
                            │ drive trực tiếp (không qua channel bus)
                            ▼
        QueryEngine.submit_message()  ──►  run_query (loop)   ← KHÔNG đụng
                            ▲
        build_query_engine(settings, cwd)   ← tách dùng chung từ ui/runtime.py
```

### 3.1 Module & file

```
src/openharness/a2a/
  __init__.py
  server.py
  executor.py
  card.py
  sessions.py
  events.py
  push.py
  config.py
```

Thay đổi code hiện có (đường nối duy nhất):
- **`src/openharness/engine/factory.py`** (MỚI): tách `async build_query_engine(settings, cwd, *, overrides) -> QueryEngine` ra khỏi `ui/runtime.py` (1254 dòng). Gom phần lắp ráp: `api_client` (resolve từ settings) + `tool_registry` (`create_default_tool_registry` + `McpClientManager.connect_all` + plugin tools) + `PermissionChecker` + `HookExecutor`. `ui/runtime.py` và `a2a/server.py` cùng gọi hàm này (hết nhân bản logic).
  - *Lưu ý*: hàm async vì `mcp_manager.connect_all()` là async.
- **`src/openharness/cli.py`**: thêm command `a2a-serve`.

## 4. Mô hình Session & Task

```
SessionManager (a2a/sessions.py)
  contextId  ──►  QueryEngine (lịch sử + tool_metadata + session-memory riêng)
                  tất cả tạo từ CÙNG build_query_engine(settings, cwd)

TaskStore (a2a-sdk: InMemoryTaskStore)
  taskId     ──►  Task(state, artifacts, history)

Per-task runtime (a2a/executor.py + QueueManager của a2a-sdk)
  taskId     ──►  background asyncio.Task + EventQueue bền + pending_input Future (chỉ khi input-required)
```

- **contextId** (A2A cấp) → tra `SessionManager`; chưa có → dựng `QueryEngine` mới; có rồi → tiếp tục hội thoại đa lượt. Đây là "nhiều session riêng biệt của 1 agent".
- **taskId** → một lần `submit_message`. Nhiều task song song = nhiều `submit_message` trên các QueryEngine khác nhau (an toàn về trạng thái hội thoại).
- **cwd chung (2a)**: mọi session dùng chung cwd. Rủi ro giẫm chân khi ghi file song song được chấp nhận ở v1 (agent thiên hỏi-đáp/đọc/phân tích). 2b (worktree/session) để sau.

## 5. Luồng dữ liệu

### 5.1 Ánh xạ sự kiện (`events.py`)

| Harness `StreamEvent` | A2A event | Ghi chú |
|---|---|---|
| (bắt đầu run) | `TaskStatusUpdateEvent(working)` | |
| `AssistantTextDelta(text)` | `TaskArtifactUpdateEvent(append=true)` | stream kết quả cuối từng mảnh vào artifact "response" |
| `ToolExecutionStarted(name)` | `TaskStatusUpdateEvent(working, "🔧 name…")` | tiến trình |
| `ToolExecutionCompleted` | `TaskStatusUpdateEvent(working, "✓ name")` | tiến trình |
| `StatusEvent` / `CompactProgressEvent` | `TaskStatusUpdateEvent(working, msg)` | nén/retry/thông báo |
| `AssistantTurnComplete` | (flush artifact) | hết một lượt model |
| (loop kết thúc, không còn tool) | `TaskUpdater.complete()` → `completed` + artifact `lastChunk=true` | |
| `ErrorEvent` / exception | `TaskUpdater.failed()` → `failed` | message đã làm sạch |

→ Hai dòng song song: **sự kiện tiến trình** (status updates) + **kết quả cuối stream dần** (artifact append → đóng bằng lastChunk).

### 5.2 send vs stream

Executor **chỉ enqueue event**; `DefaultRequestHandler` quyết: `message/stream` → SSE realtime; `message/send` → buffer → trả `Task` cuối. **Một logic phục vụ cả hai.**

### 5.3 input-required (phần khó nhất)

QueryEngine nhận callback `ask_user_prompt(question) -> str`. Khi agent gọi (giữa task):

```
Task run = background asyncio.Task do per-task runtime sở hữu
           (KHÔNG buộc vào 1 HTTP request) → emit vào per-task EventQueue (QueueManager)
                          │
   agent gọi ask_user_prompt(question)
     1. emit TaskStatusUpdateEvent(input-required, message=question)
     2. await pending_input[taskId]  (asyncio.Future)   → run TREO, vẫn sống
                          │
   client gửi message/send MỚI cùng taskId + answer
     executor.execute() thấy pending_input[taskId] tồn tại
       → KHÔNG khởi động run mới
       → pending_input[taskId].set_result(answer)
                          │
   callback trả về answer → loop chạy tiếp → emit tiếp vào CÙNG EventQueue
```

Điều kiện để chạy đúng với full lifecycle:
- Run **sống độc lập với HTTP request** + **per-task EventQueue bền** (`QueueManager`) → SSE rớt thì client `tasks/resubscribe` gắn lại, không mất event.
- Follow-up message được route để **resolve Future**, không tạo engine run mới.

> 🔴 **RỦI RO TÍCH HỢP #1** — cách `DefaultRequestHandler` route message follow-up vào task đang treo, và API chính xác `QueueManager`/`resubscribe`/`TaskUpdater`. **Phải verify bằng spike trước khi xây phần còn lại** (xem §8, làm task đầu tiên).

### 5.4 Permission trên server (3a)

`permission_prompt` chạy **phi-tương-tác** theo policy cấu hình (allow an toàn / deny nguy hiểm / FULL_AUTO tùy `A2AServerSettings`). `input-required` **chỉ** dành cho `AskUserQuestion`. (3b — bọc cả permission thành input-required — để sau.)

## 6. Agent Card · Auth · Push · Cancel

### 6.1 Agent Card (`card.py`)
`/.well-known/agent-card.json` (route do a2a-sdk lo). Dựng từ Settings + `A2AServerSettings`:
- `name`, `description`, `version`, `url`, `preferredTransport: JSONRPC`
- `capabilities`: `streaming=true`, `pushNotifications=true`
- `defaultInputModes/OutputModes`: `["text/plain"]`
- `skills`: **1** `AgentSkill` tổng quát (id, name, description, tags, examples)
- `securitySchemes`/`security`: bearer nếu bật auth

### 6.2 Auth (`config.py` + middleware)
Bearer token đơn tùy chọn. Inject qua env `OPENHARNESS_A2A_AUTH_TOKEN` (KHÔNG bake vào image). Có token → khai securityScheme + Starlette middleware kiểm `Authorization: Bearer …`. Không có → mở (dev).

### 6.3 Push (`push.py`)
`tasks/pushNotificationConfig/{set,get,list,delete}` dùng store + sender của a2a-sdk. Task đổi trạng thái (terminal hoặc input-required khi client offline) → POST `Task` tới webhook (httpx). v1: in-memory config store.

### 6.4 Cancel (`tasks/cancel`)
`executor.cancel()` → hủy background asyncio.Task của taskId (mirror `bridge._interrupt_session`), cleanup `pending_input` Future, emit `TaskStatusUpdateEvent(canceled, final)`. `run_query` đã xử lý `CancelledError` → không để tool_use mồ côi.

## 7. Testing

- **Stub `api_client`**: một `SupportsStreamingMessages` giả, phát kịch bản cố định (text deltas → 1 tool call → 1 `AskUserQuestion` → text cuối). **Không gọi LLM thật** → test nhanh, tất định.
- **Unit**: bảng map event (§5.1), `card.py`, auth middleware, push dispatcher.
- **Integration** (`tests/test_a2a/`): spin Starlette app + stub client; gọi qua httpx / a2a-sdk client → assert: vòng đời task, chunk streaming, **input-required → resume**, `tasks/get`, cancel, push tới webhook giả.
- **Manual**: A2A CLI client của bạn ↔ `oh a2a-serve` — full flow: card → stream (deltas + tool status) → làm rõ (input-required) → cancel → push tới webhook local.
- **Spike (rủi ro #1)**: test riêng & **làm trước tiên** — input-required resume + `resubscribe` với a2a-sdk thật.

## 8. Rủi ro & cách giảm

| # | Rủi ro | Giảm thiểu |
|---|---|---|
| 1 | API a2a-sdk (route follow-up vào task treo; `QueueManager`/`resubscribe`/`TaskUpdater`) còn tiến hóa | **Spike đầu tiên**, pin version cụ thể, verify trước khi xây tiếp |
| 2 | input-required + nhiều subscriber + resubscribe phức tạp | Per-task EventQueue bền; viết integration test sớm |
| 3 | cwd chung → race khi ghi file song song | Chấp nhận v1 (2a); để 2b (worktree) làm nâng cấp |
| 4 | Dependency mới `a2a-sdk` | Pin version; starlette/sse-starlette/uvicorn/httpx đã có sẵn trong lock |

## 9. Dependencies

- **Thêm top-level**: `a2a-sdk` (pin version cụ thể khi plan; verify API trong spike).
- **Đã có sẵn (lock)**: `starlette`, `sse-starlette`, `uvicorn`, `aiohttp`, `httpx`.

## 10. Tiêu chí thành công

A2A CLI client của bạn, chạy với `oh a2a-serve`, có thể:
1. Lấy Agent Card.
2. `message/stream`: thấy text deltas + status tool theo thời gian thực, nhận artifact kết quả cuối.
3. Kích hoạt một luồng `AskUserQuestion` → nhận `input-required` → gửi follow-up cùng taskId → task chạy tiếp tới `completed`.
4. `tasks/get` trả đúng trạng thái; `tasks/cancel` hủy được task đang chạy.
5. Đăng ký webhook → nhận push notification khi task đổi trạng thái.
6. Bearer auth: thiếu/sai token → 401; đúng token → chạy.

## 11. Phân pha gợi ý (cho writing-plans)

1. **Spike** xác minh a2a-sdk (input-required resume + resubscribe). [chặn các pha sau]
2. `engine/factory.py` + refactor `ui/runtime.py` dùng chung (test TUI không hồi quy).
3. Server + Agent Card + `message/send` đồng bộ (stub client). + `oh a2a-serve`.
4. Streaming: `message/stream` + map event + artifact kết quả cuối.
5. input-required đầy đủ (background run + per-task queue + Future + resubscribe).
6. `tasks/get` + `tasks/cancel`.
7. Push notification + config endpoints.
8. Auth bearer + error handling + làm sạch message.
9. Hoàn thiện test (unit + integration) + chạy manual với CLI client của bạn.
