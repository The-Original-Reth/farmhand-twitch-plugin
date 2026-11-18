"""
The Twitch extra "Stream title from what's printing" (twitch_title.py): the sign-in to Twitch (device code flow), the
title built from what the farm prints, and it set on the channel while live. Twitch is a stand-in (FakeTwitch).
"""
from __future__ import annotations

import time

import pytest

from streamer import store, twitch_title
from streamer.live_stream.sources import remember

from .conftest import wait_until

CID = "abcdefghij0123456789"
SECRET = "s3cr3tsecretsecret00"


class FakeTwitch:
    """Twitch's id.twitch.tv and Helix, as the plugin uses them: each call remembered."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None, dict | None, dict]] = []
        self.typed = False  # the code typed on twitch.tv/activate
        self.denied = False
        self.token_n = 0
        self.titles: list[str] = []
        self.expired_tokens: set[str] = set()

    def __call__(self, method, url, form=None, body=None, headers=None):
        self.calls.append((method, url, form, body, headers or {}))
        if url.endswith("/oauth2/device"):
            return 200, {"device_code": "dev-1", "user_code": "ABCD-EFGH", "verification_uri": "https://www.twitch.tv/activate",
                         "expires_in": 1800, "interval": 1}
        if url.endswith("/oauth2/token"):
            if form.get("grant_type", "").endswith("device_code"):
                if self.denied:
                    return 400, {"message": "access_denied"}
                if not self.typed:
                    return 400, {"message": "authorization_pending"}
            self.token_n += 1
            return 200, {"access_token": f"tok-{self.token_n}", "refresh_token": f"ref-{self.token_n}", "expires_in": 14000}
        if url.endswith("/oauth2/validate"):
            return 200, {"login": "farmtest"}
        if url.endswith("/oauth2/revoke"):
            return 200, {}
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
        if token in self.expired_tokens:
            return 401, {"message": "Invalid OAuth token"}
        if url.endswith("/helix/users"):
            return 200, {"data": [{"id": "4242", "login": "farmtest"}]}
        if "/helix/channels?broadcaster_id=4242" in url and method == "PATCH":
            self.titles.append(body["title"])
            return 204, {}
        return 404, {"message": "not found"}


@pytest.fixture()
def twitch(monkeypatch, plugin):
    fake = FakeTwitch()
    monkeypatch.setattr(twitch_title, "_http", fake)
    twitch_title.sign_in.cancel()
    twitch_title.keeper.forget_title()
    twitch_title.keeper._validated = 0.0
    return fake


def signed_in(api, twitch):
    assert api.put("/api/stream/twitch/app", json={"client_id": CID, "client_secret": SECRET}).status_code == 200
    page = api.post("/api/stream/twitch/sign-in").json()
    assert page["signing_in"]["code"] == "ABCD-EFGH" and page["signing_in"]["url"] == "https://www.twitch.tv/activate"
    twitch.typed = True
    assert wait_until(lambda: api.get("/api/stream/twitch").json()["signed_in_as"] == "farmtest", timeout=5)


# ------------------------------------------------------------------ the title, from what's printing


@pytest.mark.parametrize("file, name", [
    ("Frog.gcode", "Frog"),
    ("/gcodes/Benchy_0.4n_0.2mm_PLA_MK4S_1h20m.bgcode", "Benchy"),
    ("Cable clip_PETG_2h5m.gcode", "Cable clip"),
    ("plate_1.3mf", "plate 1"),
    (None, None),
])
def test_a_prints_name_is_its_files_without_what_the_slicer_adds(file, name):
    assert twitch_title.model_name(file) == name


def test_the_title_says_whats_printing_and_fits_twitch():
    assert twitch_title.compose([], "", "") == twitch_title.DEFAULT_IDLE
    assert twitch_title.compose([], "", "Farm resting") == "Farm resting"
    assert twitch_title.compose([("VT 796", "Frog"), ("V2 BOG", None)], "", "") == "Printing now: Frog on VT 796, V2 BOG"
    assert twitch_title.compose([("VT 796", "Frog")], "{count} printing: {prints} | !farm", "") == "1 printing: Frog on VT 796 | !farm"
    many = [(f"Printer {i}", f"A rather long model name {i}") for i in range(12)]
    title = twitch_title.compose(many, "", "")
    assert len(title) <= twitch_title.TITLE_MAX and title.endswith("more") and "Printer 0" in title


def test_the_farm_title_asks_every_printer_farmhand_knows(plugin, farmhand):
    remember(store.store(), {"printers": list(farmhand.cameras.values())})
    farmhand.prints[2] = {"state": "printing", "progress": 3, "file": "Hook_0.6n_PETG.bgcode", "error": None}
    assert twitch_title.farm_title(store.store(), "", "") == "Printing now: Hook on Core One, Frog on VT 1190"
    farmhand.prints[1] = farmhand.prints[2] = {"state": None, "progress": None, "file": None, "error": None}
    assert twitch_title.farm_title(store.store(), "", "Idle farm") == "Idle farm"


# ------------------------------------------------------------------ signing in


def test_signing_in_with_a_code_typed_on_twitch(api, twitch):
    page = api.get("/api/stream/twitch").json()
    assert page == {"client_id": "", "secret_set": False, "signed_in_as": None, "signing_in": None, "sign_in_error": None,
                    "title": {"title": None, "at": None, "error": None}}
    assert api.post("/api/stream/twitch/sign-in").status_code == 422  # (no application yet)
    assert api.put("/api/stream/twitch/app", json={"client_id": "not one!"}).status_code == 422
    signed_in(api, twitch)
    page = api.get("/api/stream/twitch").json()
    assert page["secret_set"] is True and page["signing_in"] is None and SECRET not in str(page)
    asked = [c for c in twitch.calls if c[1].endswith("/oauth2/token")]
    assert asked[-1][2]["client_secret"] == SECRET and asked[-1][2]["scopes"] == "channel:manage:broadcast"
    assert "tok-" not in str(api.get("/api/stream/twitch").json())
    # a new Client ID is a new application: signed out
    api.put("/api/stream/twitch/app", json={"client_id": "zyxwvutsrq9876543210"})
    assert api.get("/api/stream/twitch").json()["signed_in_as"] is None
    signed_in(api, twitch)
    assert api.post("/api/stream/twitch/sign-out").json()["signed_in_as"] is None
    assert any(c[1].endswith("/oauth2/revoke") for c in twitch.calls)


def test_a_sign_in_said_no_to_on_twitch_says_so(api, twitch):
    api.put("/api/stream/twitch/app", json={"client_id": CID})
    api.post("/api/stream/twitch/sign-in")
    twitch.denied = True
    assert wait_until(lambda: api.get("/api/stream/twitch").json()["sign_in_error"] == "Twitch said no to the sign-in.", timeout=5)
    assert api.get("/api/stream/twitch").json()["signing_in"] is None


# ------------------------------------------------------------------ the title kept on Twitch


def test_the_title_is_set_while_live_and_only_when_it_changes(api, twitch, farmhand, monkeypatch):
    from streamer.live_stream import stream

    remember(store.store(), {"printers": list(farmhand.cameras.values())})
    signed_in(api, twitch)
    live = {"live": False}
    monkeypatch.setattr(stream, "status", lambda: live)
    keeper = twitch_title.keeper
    assert keeper.check(store.store()) is None and twitch.titles == []  # (the extra is off)
    assert api.put("/api/stream", json={"twitch": {"title_from_printing": True, "title_idle": "Farm resting"}}).status_code == 200
    assert keeper.check(store.store()) is None and twitch.titles == []  # (not live)
    live["live"] = True
    assert keeper.check(store.store()) == "Printing now: Frog on VT 1190"
    assert keeper.check(store.store()) is None and twitch.titles == ["Printing now: Frog on VT 1190"]  # (no change)
    farmhand.prints[1] = {"state": None, "progress": None, "file": None, "error": None}
    assert keeper.check(store.store()) == "Farm resting"
    page = api.get("/api/stream/twitch").json()
    assert page["title"]["title"] == "Farm resting" and page["title"]["error"] is None
    # an access token Twitch no longer takes is refreshed and the call made again
    twitch.expired_tokens.add(store.store().json(twitch_title.AUTH_KEY)["access_token"])
    farmhand.prints[1] = {"state": "printing", "progress": 1, "file": "Owl.gcode", "error": None}
    assert keeper.check(store.store()) == "Printing now: Owl on VT 1190"
    assert any(c[2] and c[2].get("grant_type") == "refresh_token" for c in twitch.calls)


def test_set_title_now_and_whats_wrong_is_said(api, twitch, farmhand):
    remember(store.store(), {"printers": list(farmhand.cameras.values())})
    assert api.post("/api/stream/twitch/title").status_code == 422  # (not signed in)
    signed_in(api, twitch)
    page = api.post("/api/stream/twitch/title").json()
    assert page["title"]["title"] == "Printing now: Frog on VT 1190" and twitch.titles == ["Printing now: Frog on VT 1190"]
    store.store().put_json(twitch_title.AUTH_KEY, {**store.store().json(twitch_title.AUTH_KEY), "user_id": "999"})
    page = api.post("/api/stream/twitch/title").json()
    assert page["title"]["error"] == "Twitch didn't change the title (not found)."


def test_title_wording_is_checked(api):
    assert api.put("/api/stream", json={"twitch": {"title_format": "x" * 201}}).status_code == 422
    r = api.put("/api/stream", json={"twitch": {"title_format": "  Live: {prints}  "}})
    assert r.json()["settings"]["twitch"]["title_format"] == "Live: {prints}"
