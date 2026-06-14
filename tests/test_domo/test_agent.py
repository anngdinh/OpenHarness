import pytest

from domo.agent import _is_allowed_tool, make_build_engine
from domo.config import DomoConfig


def test_is_allowed_tool():
    # kept: bash, the skill tool, and any MCP-provided tool
    assert _is_allowed_tool("bash")
    assert _is_allowed_tool("skill")
    assert _is_allowed_tool("mcp__cloudflare-docs__search_cloudflare_documentation")
    # removed: everything else
    for name in ["agent", "task_create", "team_create", "send_message",
                 "write_file", "edit_file", "read_file", "web_fetch", "grep", "config"]:
        assert not _is_allowed_tool(name), name


@pytest.mark.asyncio
async def test_build_engine_wires_persona_session_and_permissions(tmp_path, fake_client_factory):
    config = DomoConfig(cwd=str(tmp_path))
    build_engine = make_build_engine(config, api_client=fake_client_factory([["hi"]]))

    engine = await build_engine("ctx-42")

    # persona embedded in the composed system prompt (build_runtime wraps it)
    assert "You are domo" in engine.system_prompt
    # per-conversation memory keyed by contextId
    assert engine.tool_metadata["session_id"] == "ctx-42"
    # domo read-mostly permission policy applied (kubectl delete blocked)
    decision = engine._permission_checker.evaluate(  # noqa: SLF001 - test introspection
        "bash", is_read_only=False, command="kubectl delete pod x"
    )
    assert not decision.allowed
    # and a read is allowed
    assert engine._permission_checker.evaluate(  # noqa: SLF001
        "bash", is_read_only=False, command="kubectl get pods"
    ).allowed
    # toolset restricted to bash + skill + MCP tools; everything else removed
    names = {t.name for t in engine._tool_registry.list_tools()}  # noqa: SLF001
    assert "bash" in names
    assert "skill" in names
    assert {"agent", "task_create", "team_create", "write_file", "web_fetch"} & names == set()
    assert all(n in {"bash", "skill"} or n.startswith("mcp__") for n in names), names
