# LangGraph Harness (lgharness) — Design

**Date:** 2026-06-18
**Status:** Approved (design phase)
**Author:** brainstorming session

## Mục tiêu

Xây dựng một **agent harness CLI mới, độc lập, chạy được thật** — tương tự
OpenHarness (bản port Python của Claude Code) nhưng dùng **LangGraph** làm engine
thay cho vòng lặp `run_query` tự viết.

Phiên bản đầu (v1) tập trung vào **xương sống**: agent loop + một vài tool cơ bản
+ permission + REPL. Mục tiêu kép: (a) có một harness CLI dùng được, (b) hiểu
được cách dựng agent loop bằng đúng pattern của LangGraph.

### Phi mục tiêu (v1)

Các phần sau **cố ý để dành cho v2**, ghi rõ để tránh scope-creep:
streaming token ra terminal, persistence xuống đĩa (SqliteSaver), multi-agent /
subagent, skills, plugins, hooks, MCP, memory, compaction, các tool nâng cao
(edit/glob/grep), UI React. Provider non-OpenAI (Anthropic/Ollama native).

## Quyết định cốt lõi

| Hạng mục | Quyết định | Lý do |
|----------|-----------|-------|
| Phạm vi | Harness CLI mới, độc lập, chạy thật | Không port toàn bộ OpenHarness, không thay engine repo cũ |
| Provider | OpenAI-compatible (`ChatOpenAI` + `base_url`) | Hợp hạ tầng hiện có |
| Engine | Tự xây `StateGraph` (llm ↔ tools) | Hiểu đúng agent loop; tránh `create_react_agent` prebuilt giấu mất loop |
| Permission | `interrupt()` native + `InMemorySaver` | Đúng pattern human-in-the-loop của LangGraph; dễ nâng cấp persistence v2 |
| Tools | Thuần `@tool` của LangChain, chỉ 3 tool | Đủ để kiểm chứng agent loop + permission; tool đầy đủ làm sau |
| Bố cục code | Mirror cấu trúc package OpenHarness | Dễ import, dễ đối chiếu |
| Vị trí | `src/lgharness/` trong git worktree mới | Tách biệt, không đụng `src/openharness` |

## Kiến trúc đồ thị (agent loop)

`StateGraph(MessagesState)` với 2 node + conditional routing:

```
        START
          │
          ▼
      ┌───────┐   tool_calls rỗng → END
      │  llm  │ ──────────────────────► END
      └───────┘
          │ có tool_calls
          ▼
      ┌───────┐
      │ tools │ ──(interrupt nếu cần xin phép)──► REPL hỏi user ──► resume
      └───────┘
          │ (đã có ToolMessage)
          └──────────► quay lại llm
```

- **State:** `MessagesState` dựng sẵn (`messages` + reducer `add_messages`). Đủ cho v1.
- **Node `llm`:** gọi chat model (đã `bind_tools`), trả 1 `AIMessage`. Không có
  `tool_calls` → đi tới `END`.
- **Node `tools`:** đọc `tool_calls` của AIMessage cuối; với mỗi call: permission
  check → nếu cần thì `interrupt()` → execute → tạo `ToolMessage`. Quay lại `llm`.
- **Routing:** conditional edge sau `llm` (dùng `tools_condition` dựng sẵn hoặc
  hàm tự viết kiểm tra `last_message.tool_calls`).
- **Compile:** `graph.compile(checkpointer=InMemorySaver())`. Mỗi phiên REPL =
  một `thread_id`.

**Khác biệt cốt lõi so với OpenHarness:** OpenHarness có *một* hàm `run_query`
cuốn cả vòng lặp; LangGraph tách thành node và để runtime của nó lo việc lặp +
tạm dừng/khôi phục. Permission không còn là `await prompt()` giữa loop, mà là
`interrupt()` đẩy quyền điều khiển ra REPL rồi `Command(resume=...)` quay lại.

**Lưu ý: KHÔNG dùng `ToolNode` dựng sẵn.** Vì permission/interrupt phải chen vào
*giữa* "model yêu cầu tool" và "tool thật sự chạy", nên `tools_node` được tự viết.

## Vòng đời một lượt chat & cơ chế interrupt

```
user nhập text
   │
   ▼
QueryEngine.submit_message(text)
   │  config = {"configurable": {"thread_id": <session>}}
   ▼
graph.stream({"messages":[HumanMessage(text)]}, config)
   │
   ├─ llm_node   → AIMessage (có/không tool_calls)
   ├─ tools_node → với mỗi tool_call:
   │      decision = checker.evaluate(...)
   │      • allowed                → execute() → ToolMessage
   │      • requires_confirmation  → interrupt({...}) ──┐
   │      • denied                 → ToolMessage(is_error)│
   │                                                      │
   ▼                                                      │
stream kết thúc với __interrupt__  ◄─────────────────────┘
   │
REPL hiển thị prompt xin phép → user y/n
   │
graph.stream(Command(resume=<bool>), config)   # chạy LẠI tools_node từ đầu
   │
   └─ tiếp tục tới khi llm không còn tool_calls → END
```

### Hai điểm tế nhị của `interrupt()`

1. **Node chạy lại từ đầu sau resume.** Khi `interrupt()` được resume, LangGraph
   chạy lại *toàn bộ* `tools_node` từ dòng đầu (không phải từ dòng `interrupt()`).
   **Xử lý v1:** trong `tools_node`, gom các giá trị interrupt — gọi `interrupt()`
   cho *tất cả* tool_call cần phép trong một lần (LangGraph hỗ trợ nhiều interrupt
   đồng thời, resume bằng map), rồi mới execute. Tránh chạy lại tool đã thực thi.

2. **Bắt buộc có checkpointer.** `interrupt()` yêu cầu checkpointer. `InMemorySaver`
   đủ cho v1 — state sống trong RAM theo `thread_id`, mất khi thoát process (đúng
   "không persistence"). Nâng lên `SqliteSaver` ở v2 chỉ đổi một dòng compile.

### Permission mode

- `full_auto`: bỏ qua interrupt, chạy thẳng mọi tool.
- `default`: tool mutating (write/bash) → interrupt xin phép; tool read-only
  (read) → chạy thẳng.
- `plan`: chặn mọi tool mutating (trả `ToolMessage` báo lỗi, không hỏi).

## Tools (thuần LangGraph, tối thiểu)

Tool định nghĩa bằng decorator `@tool` của LangChain — **không** port abstraction
`BaseTool`/`ToolRegistry` của OpenHarness ở v1.

```python
from langchain_core.tools import tool

@tool
def read_file(path: str) -> str:
    """Read a text file from the local repository."""
    ...

@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file (overwrites)."""
    ...

@tool
def bash(command: str) -> str:
    """Run a shell command and return its output."""
    ...
```

**Bộ tool v1 — 3 tool, đủ test cả hai nhánh permission:**

| Tool | read-only | cần xin phép (default) | dùng để test |
|------|-----------|------------------------|--------------|
| `read_file` | ✅ | không | nhánh chạy-thẳng |
| `write_file` | ❌ | có | nhánh interrupt xin phép |
| `bash` | ❌ | có | nhánh interrupt + side-effect thật |

**Cách `tools_node` biết tool nào cần phép:** vì tool là `@tool` thuần (không có
cờ `is_read_only`), dùng một danh sách tên read-only đơn giản trong `permissions/`
(ví dụ `READ_ONLY_TOOLS = {"read_file"}`). `tools_node` tra tên trong danh sách
đó để quyết định interrupt hay không.

`bash` chạy qua `asyncio.create_subprocess_shell` với timeout.

## Bố cục package (mirror OpenHarness)

```
src/lgharness/
  __init__.py
  __main__.py              # python -m lgharness
  cli.py                   # entrypoint REPL (mỏng)

  engine/                  # 🧠 LangGraph thay cho query loop tự viết
    __init__.py            # export QueryEngine, stream events (lazy)
    graph.py               # build_graph(): StateGraph llm↔tools + compile(InMemorySaver)
    nodes.py               # llm_node, tools_node (interrupt + permission ở đây)
    query_engine.py        # QueryEngine: ôm graph + thread_id, expose submit_message()/resume()
    stream_events.py       # AssistantMessage / ToolExecutionStarted/Completed / PermissionRequest / ErrorEvent

  tools/                   # 🔧 tool thuần @tool
    __init__.py            # DEFAULT_TOOLS = [read_file, write_file, bash]
    fs.py                  # read_file, write_file
    shell.py               # bash

  permissions/             # 🛡️ mirror permissions/
    __init__.py
    checker.py             # PermissionChecker.evaluate() -> PermissionDecision (rút gọn)
    modes.py               # PermissionMode: default / plan / full_auto

  prompts/                 # 📝 mirror prompts/
    __init__.py
    system_prompt.py       # build_system_prompt(cwd) -> str

  config/                  # ⚙️ mirror config/
    __init__.py
    settings.py            # Settings + PermissionMode (Pydantic, rút gọn)

  ui/                      # 🖥️ mirror ui/ (mỏng ở v1)
    __init__.py
    repl.py                # vòng lặp terminal: nhập → chạy graph → bắt interrupt → resume

  model.py                 # ChatOpenAI(base_url, api_key, model).bind_tools(DEFAULT_TOOLS)
```

## QueryEngine, REPL & config

### `config/settings.py` (Pydantic, tối thiểu)

```python
class Settings(BaseModel):
    base_url: str                                       # endpoint OpenAI-compatible
    api_key: str                                        # OPENAI_API_KEY
    model: str = "gpt-4o-mini"
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    max_turns: int = 25                                 # chặn loop vô hạn
```

Đọc từ env var (`OPENAI_API_KEY`, `OPENAI_BASE_URL`) + override bằng flag CLI.
Không file config phức tạp ở v1.

### `engine/query_engine.py`

```python
class QueryEngine:
    def __init__(self, settings):
        self._graph = build_graph(settings)            # compile(checkpointer=InMemorySaver())
        self._thread_id = uuid4().hex
        self._config = {"configurable": {"thread_id": self._thread_id}}

    async def submit_message(self, text) -> AsyncIterator[StreamEvent]:
        # stream graph với HumanMessage(text); dịch node updates -> StreamEvent
        # khi gặp __interrupt__ → yield PermissionRequest rồi dừng

    async def resume(self, decision) -> AsyncIterator[StreamEvent]:
        # graph.stream(Command(resume=decision)) → tiếp tục
```

`QueryEngine` dịch sự kiện node của LangGraph (`graph.stream(..., stream_mode="updates")`)
thành `StreamEvent` — giữ REPL tách biệt khỏi chi tiết LangGraph.

### `engine/stream_events.py` (mirror OpenHarness, dataclass tối giản)

- `AssistantMessage(text)` — model trả lời (v1 lấy nguyên message, chưa stream token).
- `ToolExecutionStarted(tool_name, tool_input)`
- `ToolExecutionCompleted(tool_name, output, is_error)`
- `PermissionRequest(tool_name, tool_input, reason)` — tín hiệu interrupt, REPL bắt cái này.
- `ErrorEvent(message)`

### `ui/repl.py` (dùng `rich` đã có sẵn)

```python
while True:
    text = input("› ")
    if text in {"/exit", "/quit"}: break
    async for ev in engine.submit_message(text):
        if isinstance(ev, PermissionRequest):
            ok = ask_yes_no(ev)                        # hỏi y/n ở terminal
            async for ev2 in engine.resume(ok):        # resume graph
                render(ev2)
        else:
            render(ev)
```

v1 xử lý một permission request mỗi lần cho đơn giản; nếu node phát nhiều interrupt
cùng lúc, REPL hỏi lần lượt rồi resume bằng map (đã tính ở phần interrupt).

### `cli.py` / `__main__.py`

Parse flag (`--model`, `--base-url`, `--permission-mode`), dựng `Settings`, tạo
`QueryEngine`, chạy `repl()`. Entry point: `python -m lgharness`.

## Dependencies

```
langgraph>=0.2          # StateGraph, interrupt, Command, InMemorySaver, MessagesState
langchain-openai>=0.2   # ChatOpenAI (trỏ base_url tới endpoint OpenAI-compatible)
langchain-core          # @tool, message types (kéo theo bởi 2 cái trên)
```

`rich` và `pydantic` đã có sẵn trong repo.

## System prompt

`prompts/system_prompt.py` — `build_system_prompt(cwd) -> str`, ngắn gọn:
"You are a coding assistant. You have tools: read_file, write_file, bash. cwd=…".
Không port toàn bộ system prompt đồ sộ của OpenHarness.

## Testing (pytest + pytest-asyncio)

- `test_graph.py` — agent loop: model trả tool_call → tools_node chạy → quay lại
  llm → kết thúc khi không còn tool_call. **Dùng FakeChatModel** (kịch bản tool_call
  định sẵn), không gọi mạng thật.
- `test_permissions.py` — `checker.evaluate`: read_file không interrupt;
  write_file/bash (default) → `requires_confirmation`; full_auto → allow; plan → block.
- `test_interrupt.py` — graph gặp write_file ở default mode → stream trả
  `__interrupt__`; resume `True` → tool chạy; resume `False` → ToolMessage báo từ
  chối, không side-effect.
- `test_tools.py` — read_file/write_file/bash hoạt động đúng trên `tmp_path`.

## Tiêu chí thành công (verifiable)

1. `python -m lgharness` mở REPL, chat được với endpoint OpenAI-compatible thật.
2. "đọc file X" → model gọi `read_file` → chạy thẳng (không hỏi phép) → trả nội dung.
3. "tạo file Y" → model gọi `write_file` → REPL **hỏi y/n** → `y` tạo file, `n`
   không tạo, model nhận biết bị từ chối.
4. `full_auto` → không hỏi phép; `plan` → tool mutating bị chặn.
5. Toàn bộ pytest xanh (không gọi mạng — dùng fake model).
