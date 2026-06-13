# domo — Domain Assistant Agent over A2A — Design Spec

- **Ngày**: 2026-06-13
- **Branch**: `agentbase-harness`
- **Trạng thái**: Approved (chờ review spec) → tiếp theo: writing-plans
- **Liên quan**: dùng lại transport từ `docs/superpowers/specs/2026-06-13-a2a-server-design.md` (core `openharness.a2a`, Tasks 1–9 đã build & test xanh)

## 1. Mục tiêu

`domo` là một **app agent độc lập** (package top-level, kiểu `ohmo`) dựng trên harness OpenHarness, expose một **trợ lý domain** qua **A2A protocol**. Trợ lý có nhiều **skill** kiến thức về các product, nhiều **MCP** truy xuất datasource, và khả năng **kiểm tra hạ tầng (kubectl)** — giúp user tra cứu thông tin & trạng thái.

Quyết định kiến trúc đã chốt: **Hướng B** — app riêng **dùng lại** transport `openharness.a2a` (không nhúng agent vào core); **A1** — tiêm một factory `build_engine(context_id)` vào core transport (điểm tiêm duy nhất), app chỉ định nghĩa agent + factory + chạy server.

### Phạm vi v1
- App `domo` với CLI `domo serve` chạy A2A server.
- Trợ lý domain: skills sản phẩm (bundle) + datasource MCP (HTTP, operator-config) + kubectl (Bash + permission đọc-là-chính).
- Multi-user; **contextId = một user/hội thoại**; **memory per-hội-thoại** qua session memory keyed = contextId.
- Bearer auth chung (operator-set).
- Deploy Docker.

### Non-goals (v1, YAGNI)
- **input-required** (hỏi-lại treo task) — phụ thuộc core Task 11 (chưa làm); v1 agent hỏi làm-rõ *inline trong câu trả lời*, `ask_user_prompt=None`.
- Per-user token / user_id-từ-auth (v1 contextId=user là đủ).
- Một user nhiều hội thoại tách biệt với memory gộp.
- Ghi/mutate hạ tầng (chỉ đọc).
- Worktree per-session (giữ shared cwd, 2a).

## 2. Quyết định đã chốt

| # | Quyết định | Chọn |
|---|---|---|
| Vị trí agent | core vs app riêng | **App riêng (Hướng B)** |
| Tích hợp transport | tiêm factory vs tự ráp | **A1: tiêm `build_engine` vào core** |
| Caller/session | — | **Nhiều user; contextId = user/hội thoại** |
| Memory | — | **Per-hội-thoại qua session memory (key=contextId)**; kiến thức domain = skills bundle (shared) |
| Tên app | — | **`domo`** |
| kubectl | MCP vs Bash | **Bash tool + permission denied_commands** |
| Datasource MCP | bake vs runtime | **HTTP, sinh runtime từ env (không bake secret)** |
| input-required | v1 | **Hoãn (chờ core Task 11); v1 `ask_user_prompt=None`** |

## 3. Kiến trúc

```
   A2A client (CLI client của bạn / frontend nội bộ)
        │  HTTP + JSON-RPC + SSE
        ▼
   openharness.a2a  (core transport — ĐÃ BUILD)
   build_asgi_app(..., build_engine=<domo factory>)   ← ĐIỂM TIÊM A1
        │  với mỗi contextId
        ▼
   domo.agent.build_engine(context_id) -> QueryEngine
        │  gọi build_runtime(system_prompt=persona,
        │                    extra_plugin_roots=[skills plugin, runtime mcp plugin],
        │                    permission_mode=..., api_client=...)
        │  rồi set engine.tool_metadata["session_id"] = context_id
        ▼
   QueryEngine (persona + skills + datasource MCP + kubectl-via-Bash,
                memory per-hội-thoại theo contextId)
```

### 3.1 Thay đổi core (nhỏ — điểm tiêm A1)
- `src/openharness/a2a/sessions.py` — `SessionManager.__init__` nhận thêm `build_engine: Callable[[str], Awaitable[QueryEngine]] | None = None`. Nếu có → `get_or_create` dùng nó; nếu None → giữ hành vi hiện tại (`build_runtime` cố định). **Backward-compatible.**
- `src/openharness/a2a/server.py` — `build_asgi_app(..., build_engine=None)` truyền xuống `SessionManager`.
- Không đổi gì khác trong core. Các test core hiện có phải vẫn xanh (default path).

### 3.2 App `domo`
```
domo/
  __init__.py
  cli.py        # `domo serve` (+ `domo doctor`)
  config.py     # DomoConfig: provider/model/base_url, a2a host/port/token,
                #             datasource MCP template, permission policy, paths
  persona.py    # PERSONA: system prompt trợ lý-domain (hỏi làm-rõ inline)
  agent.py      # make_build_engine(config) -> async build_engine(context_id) -> QueryEngine
  mcp_runtime.py# sinh plugin .mcp.json runtime từ DomoConfig + env (datasource HTTP)
  plugin/       # plugin TĨNH bake sẵn:
    plugin.json
    skills/<product>/SKILL.md   # kiến thức product (seed 1-2 mẫu)
pyproject.toml  # thêm script `domo = "domo.cli:app"`; packages += "domo"
```

## 4. Agent factory & memory (trái tim)

`domo/agent.py` → `make_build_engine(config)` trả về `async build_engine(context_id)`:
1. Sinh/định vị các plugin root: `[domo/plugin]` (skills tĩnh) + `mcp_runtime.write_runtime_mcp_plugin(config)` (datasource HTTP, secret từ env).
2. `bundle = await build_runtime(system_prompt=PERSONA, extra_plugin_roots=roots, permission_mode=config.permission_mode, model=config.model, api_client=config.api_client, cwd=config.cwd, enforce_max_turns=True, ask_user_prompt=None)`.
3. `bundle.engine.tool_metadata["session_id"] = context_id` → **memory per-hội-thoại** (session memory ghi `~/.openharness/data/session-memory/<cwd-hash>/<contextId>.md`). Giữ shared cwd 2a (project memory cwd-keyed = chung; dùng cho kiến thức nếu cần).
4. return `bundle.engine`.

**Hai tầng memory:** kiến thức domain (shared) = skills bundle; trí nhớ hội thoại = session memory key=contextId.

**Hiệu năng:** mỗi contextId → một `build_runtime` → kết nối MCP riêng. v1 dùng datasource **HTTP MCP** (mở client, không spawn process) + kubectl-Bash (free) → rẻ. (stdio MCP per-context sẽ nặng — tránh ở v1.)

## 5. Skills · MCP · kubectl

- **Skills** (`domo/plugin/skills/<product>/SKILL.md`): kiến thức product + cách tra cứu. Model-invocable. Seed 1–2 mẫu, để TODO cho user điền thật (đánh dấu rõ là mẫu, không phải placeholder ẩn).
- **Datasource MCP** (`domo/mcp_runtime.py`): đọc `DomoConfig.datasources` (list {name, url, header_env, ...}) + env → sinh `.mcp.json` (`{"mcpServers": {name: {"type":"http","url":...,"headers":{...}}}}`) vào thư mục runtime tạm; trả path để đưa vào `extra_plugin_roots`. Secret lấy từ env (vd `DOMO_DS_<NAME>_TOKEN`), KHÔNG bake.
- **kubectl**: Bash tool + `DomoConfig` → `settings.permission`:
  - `denied_commands` (fnmatch glob): `kubectl apply*`, `kubectl delete*`, `kubectl edit*`, `kubectl scale*`, `kubectl patch*`, `kubectl rollout*`, `kubectl drain*`, `kubectl cordon*`, `kubectl uncordon*`, `kubectl exec*`, `kubectl create*`, `kubectl replace*`, `kubectl cp*`, `rm *`, `sudo *`.
  - permission mode tự-duyệt phần còn lại (read-mostly, non-interactive). Cho `kubectl get/describe/logs/top/config view`.

## 6. Server · Auth · Deploy

- **Server**: `domo serve --host --port [--cwd --model --public-url]` → `A2AServerSettings.from_env()` (override bằng flag) + `make_build_engine(config)` → `openharness.a2a.run_a2a_server(a2a_settings=..., cwd=..., build_engine=factory)`.
- **Auth**: bearer token chung qua `OPENHARNESS_A2A_AUTH_TOKEN` (đã hỗ trợ ở core transport). Per-user token để sau.
- **Deploy (Docker)**: bake `domo` + skills plugin + persona; cài `kubectl` trong image; inject env: provider key (`OPENHARNESS_OPENAI_API_KEY`), `OPENHARNESS_BASE_URL`/`OPENHARNESS_MODEL`, `OPENHARNESS_A2A_AUTH_TOKEN`, datasource secrets (`DOMO_DS_*`); **mount kubeconfig**; **volume** cho `~/.openharness/data` (session memory bền).

## 7. Testing

- **Unit**:
  - `config.py`: load DomoConfig từ env/file; defaults.
  - `mcp_runtime.py`: sinh `.mcp.json` đúng (http url/headers từ env), không lộ secret khi env thiếu.
  - `agent.py`: `build_engine(ctx)` dựng engine với system_prompt=PERSONA, `tool_metadata["session_id"]==ctx`, plugin roots đúng (dùng fake `api_client`).
  - permission policy: `PermissionChecker(config→permission)` chặn `kubectl delete x`, cho `kubectl get pods`.
- **Integration** (`tests/test_domo/`): `build_asgi_app(build_engine=domo factory, api_client=fake)` qua httpx ASGITransport → GET card 200; POST message → task `completed`; file session-memory ghi đúng theo contextId; hai contextId khác nhau → hai file/engine khác nhau.
- **Core regression**: `tests/test_a2a` vẫn xanh sau khi thêm `build_engine` (default path).
- **Manual**: A2A CLI client của bạn ↔ `domo serve` (cần provider thật + kubeconfig): tra cứu product (skill), query datasource (MCP), `kubectl get` (cho), `kubectl delete` (bị chặn).

## 8. Phụ thuộc & rủi ro

| # | Vấn đề | Xử lý |
|---|---|---|
| 1 | input-required cần core Task 11 (chưa làm) | v1 `ask_user_prompt=None` + persona hỏi inline; bật sau khi Task 11 xong |
| 2 | `build_runtime` không nhận `session_id` | set `engine.tool_metadata["session_id"]` sau khi build (đã xác nhận `_prepare_session_memory` đọc lúc submit) |
| 3 | secret datasource | sinh runtime từ env, không bake; nếu env thiếu → bỏ qua server đó + log cảnh báo |
| 4 | stdio MCP per-context nặng | v1 chỉ dùng HTTP MCP cho datasource; kubectl qua Bash |
| 5 | `extra_plugin_roots` cần plugin.json hợp lệ | runtime mcp plugin sinh kèm `plugin.json` tối thiểu |

## 9. Tiêu chí thành công

A2A CLI client của bạn, trỏ vào `domo serve`:
1. Lấy Agent Card — `name` = domo (set qua `A2AServerSettings.agent_name`); skill id giữ "harness" (tổng quát) ở v1. (Quảng cáo từng product-skill trong card = enhancement sau.)
2. Hỏi về một product → agent dùng skill trả lời.
3. Yêu cầu dữ liệu → agent gọi datasource MCP (http) lấy về.
4. `kubectl get pods` → chạy; `kubectl delete ...` → bị chặn bởi permission.
5. Hai hội thoại (contextId khác) giữ ngữ cảnh riêng (session memory tách biệt).
6. Bearer auth: thiếu/sai token → 401.

## 10. Phân pha gợi ý (cho writing-plans)

1. Core: tiêm `build_engine` vào `SessionManager` + `build_asgi_app` (test core vẫn xanh).
2. `domo/config.py` (DomoConfig + from_env).
3. `domo/persona.py` (PERSONA) + `domo/plugin/` (plugin.json + 1-2 SKILL.md mẫu).
4. `domo/mcp_runtime.py` (sinh runtime mcp plugin từ env) + test.
5. `domo/agent.py` (`make_build_engine`) + test (session_id, persona, fake client).
6. permission policy (kubectl denied_commands) + test chặn/cho.
7. `domo/cli.py` (`domo serve`/`doctor`) + pyproject script + entry.
8. Integration test (`tests/test_domo`) + core regression.
9. Dockerfile + deploy doc + manual acceptance với CLI client.
