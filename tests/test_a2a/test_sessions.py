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
