import json
from pathlib import Path

import domo
from domo.persona import PERSONA


def test_persona_nonempty_and_read_only_guidance():
    assert isinstance(PERSONA, str) and len(PERSONA) > 50
    assert "read-only" in PERSONA.lower() or "do not" in PERSONA.lower()


def test_plugin_manifest_valid():
    root = Path(domo.__file__).parent / "plugin"
    manifest = json.loads((root / "plugin.json").read_text())
    assert manifest["name"]
    skill = root / "skills" / "example-product" / "SKILL.md"
    assert skill.exists()
    assert skill.read_text().startswith("---")  # frontmatter
