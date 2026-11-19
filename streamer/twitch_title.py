"""
The Twitch stream's title, kept to Stream control's: while Farmhand's Stream control sends Twitch its layout, the title
written there (its design's title) is set as the Twitch channel's title, and set again whenever it's changed there.

Changing a channel's title takes Twitch's own API, signed in as the channel (scope channel:manage:broadcast). The
operator registers an application on https://dev.twitch.tv/console/apps once and gives its Client ID (and, for a
Confidential one, its Client Secret, so the sign-in lasts) in Twitch settings; then signs in with Twitch's device
code flow: the plugin shows a code, the operator types it on twitch.tv/activate, and the plugin picks the sign-in up.
Nothing needs to reach the plugin from outside the LAN.

The application's secret and the sign-in's tokens are kept in the plugin's settings file (mode 600) and never
answered. Stream control's title is looked at every CHECK_EVERY seconds, and only sent when it changed; the sign-in is
checked with Twitch every VALIDATE_EVERY seconds, as Twitch asks of apps.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .store import Store, store

ID = "https://id.twitch.tv/oauth2"
HELIX = "https://api.twitch.tv/helix"
SCOPE = "channel:manage:broadcast"
APP_KEY = "twitch_app"  # {client_id, client_secret}
AUTH_KEY = "twitch_auth"  # {access_token, refresh_token, expires_at, login, user_id}
TITLE_MAX = 140  # Twitch's stream title
CHECK_EVERY = 10  # seconds between looks at Stream control's title
VALIDATE_EVERY = 3600  # seconds between checks of the sign-in with Twitch
TIMEOUT = 10
CLIENT_ID = re.compile(r"^[A-Za-z0-9]{10,60}$")


class TwitchError(Exception):
    """Twitch refused, or couldn't be reached: `message` in plain words. `signed_out`: the sign-in is no good any more."""

    def __init__(self, message: str, signed_out: bool = False):
        super().__init__(message)
        self.message, self.signed_out = message, signed_out


def _http(method: str, url: str, form: dict | None = None, body: dict | None = None,
          headers: dict | None = None) -> tuple[int, dict]:
    """One request to Twitch: (status, its JSON answer, {} for none). Tests put a stand-in Twitch here."""
    data, head = None, {"Accept": "application/json", **(headers or {})}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        head["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        head["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise TwitchError(f"Twitch couldn't be reached ({getattr(e, 'reason', e)}).") from None


def _said(answer: dict) -> str:
    return str(answer.get("message") or answer.get("error") or "no reason given")


def _as_channel(client_id: str, token: str) -> dict:
    """The headers a Helix call made as the signed-in channel carries."""
    return {"Client-Id": client_id, "Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ the application and the sign-in, as kept


def app(db: Store) -> dict:
    a = db.json(APP_KEY, {})
    return {"client_id": a.get("client_id") or "", "client_secret": a.get("client_secret") or ""}


def save_app(db: Store, client_id: str | None = None, client_secret: str | None = None, clear_secret: bool = False) -> None:
    """The Twitch application's Client ID and Secret (None: left as it is; "" Client ID: forgotten, with the sign-in).
    A new Client ID means signing in again. ValueError says what's wrong."""
    now = app(db)
    if client_id is not None:
        cid = client_id.strip()
        if cid and not CLIENT_ID.match(cid):
            raise ValueError("That doesn't look like a Twitch Client ID: copy it from your application on dev.twitch.tv "
                             "(Console → Applications → Manage).")
        if cid != now["client_id"]:
            db.put(AUTH_KEY, None)
            if not cid:
                now["client_secret"] = ""
        now["client_id"] = cid
    if clear_secret:
        now["client_secret"] = ""
    elif client_secret is not None and client_secret.strip():
        if not CLIENT_ID.match(client_secret.strip()):
            raise ValueError("That doesn't look like a Twitch Client Secret: make a New Secret on your application on "
                             "dev.twitch.tv and paste it.")
        now["client_secret"] = client_secret.strip()
    db.put_json(APP_KEY, now if now["client_id"] or now["client_secret"] else None)
    db.commit()


def _auth(db: Store) -> dict | None:
    a = db.json(AUTH_KEY, None)
    return a if isinstance(a, dict) and a.get("access_token") else None


def sign_out(db: Store) -> None:
    """Forget the sign-in (and tell Twitch the token is done with, best tried)."""
    a, cid = _auth(db), app(db)["client_id"]
    _forget_auth(db)
    keeper.forget_title()
    if a and cid:
        try:
            _http("POST", f"{ID}/revoke", form={"client_id": cid, "token": a["access_token"]})
        except TwitchError:
            pass


def _forget_auth(db: Store) -> None:
    db.put(AUTH_KEY, None)
    db.commit()


def _token_form(db: Store, **extra) -> dict:
    a = app(db)
    form = {"client_id": a["client_id"], **extra}
    if a["client_secret"]:
        form["client_secret"] = a["client_secret"]
    return form


def _kept_tokens(db: Store, answer: dict, who: dict | None = None) -> dict:
    before = _auth(db) or {}
    a = {
        "access_token": answer["access_token"],
        "refresh_token": answer.get("refresh_token") or before.get("refresh_token"),
        "expires_at": time.time() + float(answer.get("expires_in") or 3600),
        "login": (who or before).get("login"),
        "user_id": (who or before).get("user_id"),
    }
    db.put_json(AUTH_KEY, a)
    db.commit()
    return a


def _refresh(db: Store) -> dict:
    a = _auth(db)
    if not a or not a.get("refresh_token"):
        raise TwitchError("Sign in to Twitch again (Twitch settings).", signed_out=True)
    status, answer = _http("POST", f"{ID}/token", form=_token_form(db, grant_type="refresh_token", refresh_token=a["refresh_token"]))
    if status != 200 or not answer.get("access_token"):
        _forget_auth(db)
        raise TwitchError(f"Twitch ended the sign-in ({_said(answer)}). Sign in to Twitch again (Twitch settings).", signed_out=True)
    return _kept_tokens(db, answer)


def _call(db: Store, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """A Helix call as the signed-in channel, its token refreshed first when it's nearly out (or Twitch says it is)."""
    a = _auth(db)
    if not a:
        raise TwitchError("Sign in to Twitch first (Twitch settings).", signed_out=True)
    if float(a.get("expires_at") or 0) < time.time() + 300:
        a = _refresh(db)

    def ask(a: dict) -> tuple[int, dict]:
        return _http(method, f"{HELIX}{path}", body=body, headers=_as_channel(app(db)["client_id"], a["access_token"]))

    status, answer = ask(a)
    if status == 401:  # (Twitch says the token is out: refreshed, and asked once more)
        status, answer = ask(_refresh(db))
    return status, answer


# ------------------------------------------------------------------ signing in (Twitch's device code flow)


class SignIn:
    """One sign-in under way: the code to type on Twitch, asked about in the background until it's done or too late."""

    def __init__(self):
        self._lock = threading.Lock()
        self._waiting: dict | None = None  # {user_code, url, expires_at, device_code, interval}
        self._error: str | None = None
        self._run = 0

    def state(self) -> dict:
        with self._lock:
            w = self._waiting
            return {"code": w["user_code"], "url": w["url"], "expires_at": w["expires_at"]} if w else None

    def error(self) -> str | None:
        with self._lock:
            return self._error

    def start(self, db: Store) -> dict:
        cid = app(db)["client_id"]
        if not cid:
            raise ValueError("Give your Twitch application's Client ID first, and save it.")
        status, answer = _http("POST", f"{ID}/device", form={"client_id": cid, "scopes": SCOPE})
        if status != 200 or not answer.get("device_code"):
            raise ValueError(f"Twitch didn't start the sign-in ({_said(answer)}). Check the Client ID.")
        with self._lock:
            self._run += 1
            run = self._run
            self._error = None
            self._waiting = {
                "user_code": answer["user_code"], "url": answer.get("verification_uri") or "https://www.twitch.tv/activate",
                "expires_at": time.time() + float(answer.get("expires_in") or 1800),
                "device_code": answer["device_code"], "interval": max(1, int(answer.get("interval") or 5)),
            }
        threading.Thread(target=self._wait_for_it, args=(run,), daemon=True, name="twitch-sign-in").start()
        return self.state()

    def cancel(self) -> None:
        with self._lock:
            self._run += 1
            self._waiting = None

    def _wait_for_it(self, run: int) -> None:
        while True:
            with self._lock:
                w = self._waiting if self._run == run else None
            if not w:
                return
            time.sleep(w["interval"])
            if time.time() > w["expires_at"]:
                self._done(run, "The code ran out before it was typed on Twitch. Sign in again for a new one.")
                return
            db = store()
            try:
                status, answer = _http("POST", f"{ID}/token", form=_token_form(
                    db, scopes=SCOPE, device_code=w["device_code"], grant_type="urn:ietf:params:oauth:grant-type:device_code"))
            except TwitchError:
                continue  # (asked again next time round)
            if status == 200 and answer.get("access_token"):
                try:
                    who = _whoami(answer["access_token"], app(db)["client_id"])
                except TwitchError as e:
                    self._done(run, e.message)
                    return
                with self._lock:
                    if self._run != run:
                        return
                _kept_tokens(db, answer, who)
                self._done(run, None)
                keeper.poke()
                return
            if _said(answer) in ("authorization_pending", "slow_down"):
                continue
            self._done(run, "Twitch said no to the sign-in." if _said(answer) == "access_denied"
                       else f"Twitch didn't finish the sign-in ({_said(answer)}). Sign in again.")
            return

    def _done(self, run: int, error: str | None) -> None:
        with self._lock:
            if self._run == run:
                self._waiting, self._error = None, error


def _whoami(token: str, client_id: str) -> dict:
    status, answer = _http("GET", f"{HELIX}/users", headers=_as_channel(client_id, token))
    data = answer.get("data") if isinstance(answer, dict) else None
    if status != 200 or not data:
        raise TwitchError(f"Twitch didn't say whose channel this is ({_said(answer)}).")
    return {"login": data[0].get("login"), "user_id": data[0].get("id")}


sign_in = SignIn()


# ------------------------------------------------------------------ the title, kept to Stream control's


class TitleKeeper:
    """Keeps the channel's title to Stream control's, while Stream control sends Twitch its layout."""

    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._sent: str | None = None  # the title last set on Twitch
        self._sent_at: float | None = None
        self._error: str | None = None
        self._validated = 0.0

    def state(self) -> dict:
        with self._lock:
            return {"title": self._sent, "at": self._sent_at, "error": self._error}

    def forget_title(self) -> None:
        with self._lock:
            self._sent = None

    def poke(self) -> None:
        """Look again now (signed in, gone live)."""
        self._wake.set()

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stopping = False
            self._thread = threading.Thread(target=self._loop, daemon=True, name="twitch-title")
            self._thread.start()

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    def _loop(self) -> None:
        while not self._stopping:
            try:
                self.check(store())
            except Exception as e:  # noqa: BLE001 - looked at again next time round
                with self._lock:
                    self._error = f"The title couldn't be set ({e})."
            self._wake.wait(CHECK_EVERY)
            self._wake.clear()

    def check(self, db: Store, force: bool = False) -> str | None:
        """Set Stream control's title on Twitch if it changed: the title sent, or None (nothing to do: not following
        Stream control, no title written there, or not signed in). `force`: even when it's what was sent last."""
        from .live_stream import choices

        chosen = choices.chosen(db)
        title = (chosen.get("title") or "").strip()[:TITLE_MAX] if chosen.get("following") else ""
        if not title:
            with self._lock:
                self._sent = None  # (sent again once there's one: it may have been changed on Twitch meanwhile)
            return None
        a = _auth(db)
        if not a:
            with self._lock:
                self._error = "Sign in to Twitch in Twitch settings, so Stream control's title can be set on Twitch."
            return None
        with self._lock:
            if title == self._sent and not force:
                return None
        try:
            if time.time() - self._validated > VALIDATE_EVERY:
                self._validate(db)
            status, answer = _call(db, "PATCH", f"/channels?broadcaster_id={urllib.parse.quote(str(a['user_id']))}",
                                   {"title": title})
            if status not in (200, 204):
                raise TwitchError(f"Twitch didn't change the title ({_said(answer)}).")
        except TwitchError as e:
            with self._lock:
                self._error = e.message
            return None
        with self._lock:
            self._sent, self._sent_at, self._error = title, time.time(), None
        return title

    def _validate(self, db: Store) -> None:
        a = _auth(db)
        status, answer = _http("GET", f"{ID}/validate", headers={"Authorization": f"OAuth {a['access_token']}"})
        if status == 401:
            _refresh(db)
        elif status != 200:
            raise TwitchError(f"Twitch couldn't check the sign-in ({_said(answer)}).")
        self._validated = time.time()


keeper = TitleKeeper()


def page(db: Store) -> dict:
    """What the Twitch settings window shows: the application (its secret only as whether it's there), who's signed
    in, a sign-in under way, and the title last set."""
    a, signed = app(db), _auth(db)
    return {
        "client_id": a["client_id"], "secret_set": bool(a["client_secret"]),
        "signed_in_as": signed.get("login") if signed else None,
        "signing_in": sign_in.state(), "sign_in_error": sign_in.error(),
        "title": keeper.state(),
    }
