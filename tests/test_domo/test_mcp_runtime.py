import json

from domo.config import DatasourceConfig, DomoConfig
from domo.mcp_runtime import write_runtime_mcp_plugin


def test_returns_none_when_no_datasources(tmp_path):
    assert write_runtime_mcp_plugin(DomoConfig(), tmp_path) is None


def test_generates_http_mcp_with_token_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DOMO_DS_METRICS_TOKEN", "secret-tok")
    cfg = DomoConfig(datasources=[
        DatasourceConfig(name="metrics", url="https://m.test/mcp", token_env="DOMO_DS_METRICS_TOKEN")
    ])
    root = write_runtime_mcp_plugin(cfg, tmp_path)
    assert root is not None
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["name"]
    mcp = json.loads((root / ".mcp.json").read_text())
    server = mcp["mcpServers"]["metrics"]
    assert server["type"] == "http"
    assert server["url"] == "https://m.test/mcp"
    assert server["headers"]["Authorization"] == "Bearer secret-tok"


def test_skips_datasource_when_token_env_missing(tmp_path):
    cfg = DomoConfig(datasources=[
        DatasourceConfig(name="metrics", url="https://m.test/mcp", token_env="DOMO_DS_METRICS_TOKEN")
    ])
    root = write_runtime_mcp_plugin(cfg, tmp_path)
    mcp = json.loads((root / ".mcp.json").read_text())
    assert "metrics" not in mcp["mcpServers"]
