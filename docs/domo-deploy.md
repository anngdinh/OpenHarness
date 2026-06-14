# domo Deploy Guide

## What is domo?

`domo` is an A2A (Agent-to-Agent) domain-assistant server built on OpenHarness. It exposes:

- **Product skills** — bundled skill plugins (under `domo/plugin/`) for answering domain-specific questions.
- **Datasource MCPs** — HTTP MCP servers for structured data access, configured via `DomoConfig.datasources`.
- **Read-only kubectl** — infra status checks via `kubectl get`, `kubectl describe`, etc. Mutating verbs (`apply`, `delete`, `exec`, and others) are blocked by the deny-list in `domo/config.py`.

The server speaks the A2A protocol: it accepts classic `message/send` / `message/stream` JSON-RPC calls and advertises its capabilities via an Agent Card.

---

## Build

```bash
docker build -f Dockerfile.domo -t domo:latest .
```

---

## Required Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENHARNESS_OPENAI_API_KEY` | Yes | API key for the LLM provider |
| `OPENHARNESS_BASE_URL` | Yes | OpenAI-compatible endpoint (e.g. `https://api.openai.com/v1`) |
| `OPENHARNESS_MODEL` | Yes | Model ID (e.g. `gpt-4o`, `claude-3-5-sonnet-20241022`) |
| `OPENHARNESS_A2A_AUTH_TOKEN` | No | Bearer token for A2A auth; omit to run open (no auth) |
| `DOMO_MODEL` | No | Overrides `OPENHARNESS_MODEL` for the domo agent specifically |
| `DOMO_CWD` | No | Agent working directory (default: `/work` in the image) |
| `DOMO_PERMISSION_MODE` | No | Permission mode (`full_auto`, etc.; default: `full_auto`) |
| `DOMO_DS_<NAME>_TOKEN` | No | Bearer token for datasource `<NAME>` (one per datasource) |

---

## kubeconfig

Mount your kubeconfig read-only so `kubectl` can reach the cluster:

```bash
-v $HOME/.kube:/root/.kube:ro
```

Only read-only kubectl verbs are permitted. The deny-list in `domo/config.py` (`KUBECTL_DENY_PATTERNS`) blocks mutating and dangerous operations including `apply`, `delete`, `edit`, `scale`, `patch`, `rollout`, `drain`, `exec`, `attach`, `debug`, `port-forward`, `create`, `replace`, `cp`, `set`, `label`, and `annotate`.

---

## Persistent Memory

`domo` stores per-conversation session memory under `OPENHARNESS_CONFIG_DIR` (defaults to `/data/openharness` in the image). Mount a named volume for `/data` so memory survives container restarts:

```bash
-v domo-data:/data
```

---

## Example `docker run`

```bash
docker run -d --name domo -p 9100:9100 \
  -e OPENHARNESS_OPENAI_API_KEY=sk-xxx \
  -e OPENHARNESS_BASE_URL=https://your-endpoint/v1 \
  -e OPENHARNESS_MODEL=your-model \
  -e OPENHARNESS_A2A_AUTH_TOKEN=secret \
  -v $HOME/.kube:/root/.kube:ro \
  -v domo-data:/data \
  domo:latest
```

---

## Registering Datasources

Datasource MCPs are HTTP servers. Each datasource is described by a `DatasourceConfig(name, url, token_env)` entry in `DomoConfig.datasources`:

- `name` — a short identifier used in the MCP plugin.
- `url` — the base URL of the HTTP MCP server.
- `token_env` — the name of the environment variable that holds the bearer token. The token is read from the environment at startup (never baked into the image).

In v1, `datasources` is populated programmatically (e.g. by the application bootstrap that constructs `DomoConfig`). This is the primary extension point: add new `DatasourceConfig` entries to wire additional data backends into the agent.

Example: if you add `DatasourceConfig(name="inventory", url="http://inventory-mcp:8080", token_env="DOMO_DS_INVENTORY_TOKEN")`, set `-e DOMO_DS_INVENTORY_TOKEN=<token>` at container start.

---

## Connecting a Client

Point any A2A-compatible client at `http://<host>:9100`:

- **Agent Card:** `GET http://<host>:9100/.well-known/agent-card.json`
- **JSON-RPC endpoint:** accepts `message/send` and `message/stream` requests.

If `OPENHARNESS_A2A_AUTH_TOKEN` is set, include the header:

```
Authorization: Bearer <token>
```

Requests without a valid token (or with a wrong token) return `401 Unauthorized`.

---

## Manual Acceptance Checklist

These checks require a live provider, a valid kubeconfig, and an A2A client:

- [ ] Agent Card name is `"domo"` — `GET /.well-known/agent-card.json` returns `"name": "domo"`.
- [ ] Product skill works — ask a product question; verify the response uses a bundled skill.
- [ ] Datasource MCP works — request data from a configured datasource; verify the response.
- [ ] `kubectl get pods` succeeds — the agent can run read-only kubectl commands.
- [ ] `kubectl delete ...` is blocked — the agent refuses mutating kubectl verbs.
- [ ] Context isolation — two different `contextId` values maintain separate conversation memory.
- [ ] Auth enforced — requests with a wrong or missing token return `401` when `OPENHARNESS_A2A_AUTH_TOKEN` is set.
