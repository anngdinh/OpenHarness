import pytest

from lgharness.tools import DEFAULT_TOOLS, TOOLS_BY_NAME
from lgharness.tools.fs import read_file, write_file
from lgharness.tools.shell import bash


def test_registry_contents():
    assert {t.name for t in DEFAULT_TOOLS} == {"read_file", "write_file", "bash"}
    assert set(TOOLS_BY_NAME) == {"read_file", "write_file", "bash"}


@pytest.mark.asyncio
async def test_write_then_read(tmp_path):
    target = tmp_path / "note.txt"
    out = await write_file.ainvoke({"path": str(target), "content": "hello"})
    assert "hello" not in out  # returns a status, not the content
    assert target.read_text() == "hello"

    content = await read_file.ainvoke({"path": str(target)})
    assert "hello" in content


@pytest.mark.asyncio
async def test_read_missing_file(tmp_path):
    out = await read_file.ainvoke({"path": str(tmp_path / "nope.txt")})
    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_bash_echo():
    out = await bash.ainvoke({"command": "echo hi"})
    assert "hi" in out
