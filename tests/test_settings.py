"""
The Twitch plugin's settings, in its own store (secrets never answered), the saved layouts and the stream folder;
the Twitch extras, kept but not ready yet; and what Farmhand asks of every plugin.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

from streamer import config, farm, store
from streamer.live_stream.constants import SETTINGS_KEY, STREAM_KEY_KEY

from .conftest import KEY, grid

pytestmark = pytest.mark.usefixtures("stream_fresh")


# ------------------------------------------------------------------ settings, kept by the plugin


def test_settings_live_in_the_plugins_own_store_and_secrets_never_come_back(api, plugin):
    page = grid(api, [{"camera": "1:Bed"}, None])
    assert page["settings"]["key_set"] is True and KEY not in json.dumps(page)
    saved = json.loads(plugin.path.read_text(encoding="utf-8"))
    assert saved[STREAM_KEY_KEY] == KEY and json.loads(saved[SETTINGS_KEY])["cols"] == 2
    if sys.platform != "win32":
        assert oct(os.stat(plugin.path).st_mode & 0o777) == "0o600"  # only the plugin reads its key
    again = store.Store(plugin.path)  # (the plugin started again)
    assert again.get(STREAM_KEY_KEY) == KEY
    assert api.put("/api/stream", json={"clear_key": True}).json()["settings"]["key_set"] is False


def test_saved_layouts_are_kept_by_the_plugin(api):
    r = api.put("/api/layouts", json={"layouts": [{"name": "Morning", "cols": 1, "rows": 1, "cells": [{"camera": "1:Bed"}]}, "junk"]})
    assert r.status_code == 200 and [x["name"] for x in r.json()["layouts"]] == ["Morning"]
    assert api.get("/api/layouts").json()["layouts"][0]["cells"][0]["camera"] == "1:Bed"


def test_the_stream_folder_is_the_folder_the_container_is_given(api, plugin, tmp_path, monkeypatch):
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 201 and r.json()["media"]["images"] == ["logo.png"]
    assert (tmp_path / "media" / "images" / "logo.png").is_file()
    monkeypatch.setattr(config.settings, "media_dir", tmp_path / "not-mounted")
    from streamer import stream_media
    stream_media.forget()
    r = api.post("/api/stream/pictures", files={"files": ("logo.png", b"x", "image/png")})
    assert r.status_code == 503 and "isn't there" in r.json()["detail"]


# ------------------------------------------------------------------ Twitch: where it goes, and the extras to come


def test_the_stream_goes_to_twitch_only(api):
    page = api.get("/api/stream").json()
    assert page["destinations"] == [{"key": "twitch", "label": "Twitch"}] and page["settings"]["destination"] == "twitch"
    assert [r["key"] for r in page["resolutions"]] == ["720p", "1080p"]
    assert "Twitch only" in api.put("/api/stream", json={"destination": "youtube"}).json()["detail"]
    assert "youtube" not in page and "title" not in page["settings"]


def test_the_channel_name_is_kept_from_a_name_or_an_address(api):
    assert api.get("/api/stream").json()["settings"]["channel"] is None
    for typed in ("3DPrintingElves", "https://www.twitch.tv/3dprintingelves/", "twitch.tv/3DPrintingElves/videos", "@3dprintingelves"):
        assert api.put("/api/stream", json={"channel": typed}).json()["settings"]["channel"] == "3dprintingelves"
    r = api.put("/api/stream", json={"channel": "not a name!"})
    assert r.status_code == 422 and "twitch.tv/<name>" in r.json()["detail"]
    assert api.put("/api/stream", json={"channel": ""}).json()["settings"]["channel"] is None


def test_the_twitch_extras_are_kept_but_cant_be_turned_on_yet(api):
    page = api.get("/api/stream").json()
    assert page["settings"]["twitch"] == {"title_from_printing": False, "chat_commands": False, "chat_on_screen": False}
    assert page["settings"]["twitch_extras_ready"] is False
    r = api.put("/api/stream", json={"twitch": {"chat_commands": True}})
    assert r.status_code == 422 and "later version" in r.json()["detail"]
    assert api.put("/api/stream", json={"twitch": {"chat_commands": False}}).status_code == 200


# ------------------------------------------------------------------ what Farmhand asks of a plugin


def test_manifest_and_health(api, farmhand):
    m = api.get("/manifest").json()
    assert m["id"] == "twitch" and set(m["permissions"]) == {"cameras:read", "prints:read", "stream:read"}
    assert m["stream_control"] == {"path": "/api/stream-control", "site": "Twitch"}
    assert api.get("/health").text == "ok"
    farm.cameras(store.store())
    config.settings.farmhand_token = "wrong"
    try:
        farm.cameras(store.store())
        r = api.get("/health")
        assert r.status_code == 503 and "refused this plugin's token" in r.text
    finally:
        from .fake_farmhand import TOKEN
        config.settings.farmhand_token = TOKEN
