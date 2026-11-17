"""The docker-compose file builds this plugin from its own repository. Farmhand's Plugins page shows a copy of it
(frontend/src/plugins/compose/twitch.yml in Farmhand's repository): change both together."""
from __future__ import annotations

from pathlib import Path

import yaml

PLUGIN = Path(__file__).resolve().parent.parent


def test_compose_file_is_valid_and_builds_the_plugin_from_its_own_repository():
    data = yaml.safe_load((PLUGIN / "docker-compose.yml").read_text(encoding="utf-8"))
    stream = data["services"]["twitch"]
    assert stream["build"] == "https://github.com/The-Original-Reth/farmhand-twitch-plugin.git#main"
    assert stream["ports"] == ["8081:8080"]  # (8080 left for the YouTube plugin)
    assert stream["env_file"] == [{"path": "twitch.env", "required": False}]
    assert "twitch-data:/data" in stream["volumes"]
    assert "twitch-data" in data["volumes"]
