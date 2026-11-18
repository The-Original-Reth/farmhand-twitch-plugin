"""
The Twitch stream's title kept to Stream control's (twitch_title.py): the sign-in to Twitch (device code flow), and
Stream control's title set on the channel, again whenever it changes. Twitch is a stand-in (FakeTwitch).
"""
from __future__ import annotations

import time

import pytest

from streamer import store, twitch_title

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


# ------------------------------------------------------------------ Stream control's title kept on Twitch


@pytest.fixture()
def control(monkeypatch):
    """Stream control as the plugin reads it (choices.chosen): following or not, and its title."""
    from streamer.live_stream import choices

    now = {"following": True, "title": "Printing 24/7 - unless we forget to change the plate"}
    real = choices.chosen
    monkeypatch.setattr(choices, "chosen", lambda db: {**real(db), **now})
    return now


def test_stream_controls_title_is_set_on_twitch_and_again_when_it_changes(api, twitch, control):
    keeper = twitch_title.keeper
    assert keeper.check(store.store()) is None and twitch.titles == []  # (not signed in)
    assert "Sign in" in api.get("/api/stream/twitch").json()["title"]["error"]
    signed_in(api, twitch)
    assert keeper.check(store.store()) == "Printing 24/7 - unless we forget to change the plate"
    assert keeper.check(store.store()) is None  # (no change: not sent again)
    control["title"] = "Night shift"
    assert keeper.check(store.store()) == "Night shift"
    assert twitch.titles == ["Printing 24/7 - unless we forget to change the plate", "Night shift"]
    page = api.get("/api/stream/twitch").json()
    assert page["title"]["title"] == "Night shift" and page["title"]["error"] is None
    # not following Stream control (or no title there): Twitch's title left as it is; sent again once there's one
    control["following"] = False
    assert keeper.check(store.store()) is None
    control.update(following=True, title="  ")
    assert keeper.check(store.store()) is None
    control["title"] = "Night shift"
    assert keeper.check(store.store()) == "Night shift"
    # past Twitch's 140 characters: cut
    control["title"] = "x" * 200
    assert keeper.check(store.store()) == "x" * 140
    # an access token Twitch no longer takes is refreshed and the call made again
    twitch.expired_tokens.add(store.store().json(twitch_title.AUTH_KEY)["access_token"])
    control["title"] = "Day shift"
    assert keeper.check(store.store()) == "Day shift"
    assert any(c[2] and c[2].get("grant_type") == "refresh_token" for c in twitch.calls)


def test_set_title_now_and_whats_wrong_is_said(api, twitch, control):
    assert api.post("/api/stream/twitch/title").status_code == 422  # (not signed in)
    signed_in(api, twitch)
    page = api.post("/api/stream/twitch/title").json()
    assert page["title"]["title"] == control["title"] and twitch.titles == [control["title"]]
    assert api.post("/api/stream/twitch/title").json()["title"]["title"] == control["title"] and len(twitch.titles) == 2
    control["following"] = False
    r = api.post("/api/stream/twitch/title")
    assert r.status_code == 422 and "ticked in Stream control" in r.json()["detail"]
    control["following"] = True
    store.store().put_json(twitch_title.AUTH_KEY, {**store.store().json(twitch_title.AUTH_KEY), "user_id": "999"})
    assert api.post("/api/stream/twitch/title").json()["title"]["error"] == "Twitch didn't change the title (not found)."


def test_the_title_isnt_taken_from_the_plugins_own_layout(api, twitch, plugin):
    """Not following Stream control (the real chosen()): nothing is set on Twitch."""
    signed_in(api, twitch)
    assert twitch_title.keeper.check(store.store()) is None and twitch.titles == []
