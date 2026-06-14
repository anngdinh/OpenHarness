from __future__ import annotations

from openharness.channels.impl.base import resolve_channel_media_dir


def test_resolve_channel_media_dir_uses_openharness_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / ".openharness-data"
    monkeypatch.delenv("OPENHARNESS_CHANNEL_MEDIA_DIR", raising=False)
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(data_dir))

    media_dir = resolve_channel_media_dir("telegram")

    assert media_dir == data_dir / "media" / "telegram"
    assert media_dir.is_dir()
