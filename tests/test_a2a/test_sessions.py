import pytest

from openharness.a2a.sessions import SessionManager


@pytest.mark.asyncio
async def test_same_context_returns_same_engine(tmp_path, fake_client_factory):
    mgr = SessionManager(cwd=str(tmp_path), api_client=fake_client_factory([["hi"]]))
    s1 = await mgr.get_or_create("ctx-1")
    s2 = await mgr.get_or_create("ctx-1")
    assert s1.engine is s2.engine


@pytest.mark.asyncio
async def test_different_contexts_isolated(tmp_path, fake_client_factory):
    mgr = SessionManager(cwd=str(tmp_path), api_client=fake_client_factory([["a"], ["b"]]))
    a = await mgr.get_or_create("ctx-a")
    b = await mgr.get_or_create("ctx-b")
    assert a.engine is not b.engine


@pytest.mark.asyncio
async def test_build_engine_callback_is_used(tmp_path, fake_client_factory):
    calls: list[str] = []

    async def fake_build_engine(context_id: str):
        calls.append(context_id)
        from openharness.ui.runtime import build_runtime
        bundle = await build_runtime(
            cwd=str(tmp_path), api_client=fake_client_factory([["hi"]]), enforce_max_turns=True
        )
        return bundle.engine

    mgr = SessionManager(cwd=str(tmp_path), build_engine=fake_build_engine)
    s1 = await mgr.get_or_create("ctx-1")
    s2 = await mgr.get_or_create("ctx-1")
    assert s1.engine is s2.engine
    assert calls == ["ctx-1"]
