import pytest

from domo.agent import make_build_engine
from domo.config import DomoConfig


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
