from openharness.a2a.card import build_agent_card
from openharness.a2a.config import A2AServerSettings


def test_card_basic_fields():
    card = build_agent_card(A2AServerSettings(public_url="https://x.test"))
    assert card.supported_interfaces[0].url == "https://x.test/"
    assert card.capabilities.streaming is True
    assert card.capabilities.push_notifications is True
    assert len(card.skills) == 1
    assert card.skills[0].id == "harness"


def test_card_security_present_when_auth_enabled():
    card = build_agent_card(A2AServerSettings(auth_token="t"))
    assert card.security_schemes  # non-empty map when auth configured


def test_card_no_security_when_open():
    card = build_agent_card(A2AServerSettings())
    assert not card.security_schemes
