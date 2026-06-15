from openharness.a2a.config import A2AServerSettings


def test_defaults():
    s = A2AServerSettings()
    assert s.host == "127.0.0.1"
    assert s.port == 9100
    assert s.auth_token is None
    assert s.public_url == "http://127.0.0.1:9100"


def test_public_url_explicit_wins():
    s = A2AServerSettings(host="0.0.0.0", port=80, public_url="https://agent.example.com")
    assert s.public_url == "https://agent.example.com"


def test_from_env_reads_auth_token(monkeypatch):
    monkeypatch.setenv("OPENHARNESS_A2A_AUTH_TOKEN", "secret123")
    s = A2AServerSettings.from_env()
    assert s.auth_token == "secret123"
