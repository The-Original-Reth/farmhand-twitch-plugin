"""
Farmhand's Stream control (docs/plugins.md, "Stream control", in Farmhand's repository): the operator designs one stream
in Farmhand and ticks the stream plugins that send it. While this plugin is ticked, **Stream control's layout takes
over**: the stream sends Farmhand's design in place of the plugin's own layout (the grid, its squares, the music, the
holding screen...), which is kept as it is and comes back as soon as Stream control lets go. The stream key, the channel
and the Twitch extras stay the plugin's own.

The follower asks Farmhand's GET /stream/design every POLL seconds (stream:read):

    {"enabled": false}, or 403 (stream:read not granted), or 404 (a Farmhand without Stream control): the plugin's own layout
    {"enabled": true, "design": {...}, "media": {...}}: that design, its pictures and music copied into MEDIA_DIR
    no answer (Farmhand restarting, say): as it was, so the stream doesn't change because Farmhand blinked

When what's followed changes while live (Stream control on or off, a new revision saved), the stream changes as it does
for a change saved on the plugin's own page: a new picture handed over to with no break, or just the music following.
Farmhand starts and stops the stream through /api/stream-control (routes.py).

The design's files are copied by a copier of their own (one round at a time, always the newest list), never by the
asking: a long copy (fifty tracks, each passed on by Farmhand from another plugin's folder) used to hold the asking up for
a quarter of an hour, so a note that Farmhand couldn't be asked stayed on screen long after it answered again. The
design is followed at once with the files already there; once a round of copying has changed some, the stream is handed
over to them. How far a round has got is shown apart from what's wrong (copying()).
"""
from __future__ import annotations

import copy
import json
import threading
import time
import urllib.parse
from pathlib import Path

from . import config, farm, storage, stream_media
from .farmhand import FarmhandError

POLL = 5  # seconds between asking Farmhand for the design
STAMPS_FILE = ".stamps.json"  # in MEDIA_DIR: each file's stamp (Farmhand's media.stamps) as last copied
BUSY_TRIES = 4  # times a file is asked for while Farmhand says to slow down (429)
BUSY_WAIT_MOST = 10  # seconds waited at most between those
MEDIA_DIR = "stream-control"  # in the plugin's own volume (DATA_DIR): Stream control's pictures and music, as a stream folder
PICTURE_KEYS = ("cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "border_color",
                "background", "font", "color")  # (as routes.PICTURE: these changed while live, the picture is made again)
MUSIC_KEYS = ("music", "music_volume", "music_shuffle")


def _quote(name: str) -> str:
    return urllib.parse.quote(name, safe="")


def _media_names(raw, types: dict) -> list[str]:
    """The files of these types named in a list of Farmhand's media (its blank screens, and names a file can't have,
    left out)."""
    out = []
    for n in raw if isinstance(raw, list) else []:
        if stream_media.is_blank(n):
            continue
        try:
            n = stream_media._name(n, "file")
        except (ValueError, TypeError):
            continue
        if Path(n).suffix.lower() in types:
            out.append(n)
    return out


def _stamps_copied(root: Path) -> dict:
    """Each file's stamp as last copied into `root` (STAMPS_FILE), or {} when there's none to read."""
    try:
        had = json.loads((root / STAMPS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return had if isinstance(had, dict) else {}


def _not_copied(failed: list[tuple[str, str]]) -> str | None:
    """What couldn't be copied, in a few words ((name, why) each), or None when everything was."""
    if not failed:
        return None
    first = ", ".join(n for n, _ in failed[:2]) + (" …" if len(failed) > 2 else "")
    what = "file" if len(failed) == 1 else "files"
    return f"{len(failed)} of Stream control's {what} couldn't be copied from Farmhand ({first}): {failed[0][1]}"


class Follower:
    def __init__(self):
        self._lock = threading.Lock()
        self._asking = threading.Lock()  # one ask at a time (the poll, and a Go live from Farmhand)
        self._design: dict | None = None  # Stream control's design while it's followed
        self._got: tuple | None = None  # (revision, media) of the files last copied in
        self._error: str | None = None  # why Farmhand couldn't be asked, or the design can't be sent (goes on the next good ask)
        # what couldn't be copied the last time the files were (kept while they're the same; never a note that Farmhand
        # couldn't be asked, which goes as soon as it answers again)
        self._copy_problem: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # the copier: the newest (got, media) to copy, how far the round under way has got, and whether it runs in the
        # background (start(); until then, as in the tests, a check copies before it returns)
        self._wanted: tuple | None = None
        self._progress: tuple[int, int] | None = None  # (done, of) while a round is under way
        self._copy_wake = threading.Event()
        self._copier: threading.Thread | None = None
        self._background = False

    # ------------------------------------------------------------------ what the rest of the plugin reads

    def design(self) -> dict | None:
        """Stream control's design while it's followed (a copy), else None (the plugin's own layout)."""
        with self._lock:
            return copy.deepcopy(self._design)

    def following(self) -> bool:
        with self._lock:
            return self._design is not None

    def error(self) -> str | None:
        """What's wrong now: Farmhand not answering or the design not sendable, else what couldn't be copied."""
        with self._lock:
            return self._error or self._copy_problem

    def copying(self) -> str | None:
        """How far copying Stream control's files has got, while a round is under way (None otherwise)."""
        with self._lock:
            p = self._progress
        if not p:
            return None
        return f"Copying Stream control's pictures and music from Farmhand: {p[0]} of {p[1]} files"

    def media_dir(self) -> Path | None:
        """Where Stream control's pictures and music are, while it's followed (laid out as the stream folder is)."""
        return self._folder() if self.following() else None

    def page(self) -> dict:
        """For the plugin's page: {following, revision, saved_at, title, error, copying}."""
        with self._lock:
            d = self._design or {}
            out = {"following": self._design is not None, "revision": d.get("revision"), "saved_at": d.get("saved_at"),
                   "title": d.get("title")}
        return {**out, "error": self.error(), "copying": self.copying()}

    # ------------------------------------------------------------------ asking Farmhand

    def start(self) -> None:
        """Ask every POLL seconds, in the background, until stop() (the files copied by the copier meanwhile)."""
        self._stop.clear()
        self.copy_in_background()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="stream-control", daemon=True)
        self._thread.start()

    def copy_in_background(self) -> None:
        """From now on the files are copied by the copier, never while asking (before the first ask at start-up, so
        that doesn't wait for every file either)."""
        self._background = True
        if self._copier and self._copier.is_alive():
            return
        self._copier = threading.Thread(target=self._copy_rounds, name="stream-control-copier", daemon=True)
        self._copier.start()

    def stop(self) -> None:
        self._stop.set()
        self._copy_wake.set()

    def reset(self) -> None:
        """Back to the plugin's own layout, nothing asked yet (the tests' fresh start)."""
        with self._lock:
            self._design, self._got, self._error, self._copy_problem = None, None, None, None
            self._wanted, self._progress = None, None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as e:  # noqa: BLE001 - a bad answer must never end the asking
                print(f"stream: asking Stream control failed ({e})", flush=True)
            self._stop.wait(POLL)

    def check(self) -> None:
        """Ask Farmhand for the design once, follow what it says (at once, with the files already there), and change the
        stream when that changes it. New or changed files are left to the copier (copied here only before start())."""
        with self._asking:
            try:
                answer = farm.client().stream_design()
            except FarmhandError as e:
                if e.status in (403, 404):  # stream:read not granted, or a Farmhand without Stream control
                    self._follow(None)
                else:  # Farmhand not answering: carry on as it was
                    with self._lock:
                        self._error = f"Couldn't ask Farmhand's Stream control: {e.short}"
                return
            if not isinstance(answer, dict) or answer.get("enabled") is not True or not isinstance(answer.get("design"), dict):
                self._follow(None)
                return
            design, media = answer["design"], answer.get("media") if isinstance(answer.get("media"), dict) else {}
            got = (design.get("revision"), json.dumps(media, sort_keys=True))
            with self._lock:
                # (new or changed files, or some that couldn't be copied last time: a round of copying, unless one for
                # this list is waiting already)
                fresh = got != self._got and (self._wanted is None or self._wanted[0] != got)
                if fresh:
                    self._wanted = (got, media)
            if fresh and not self._background:
                self._copy_round(send=False)  # (copied first: the design is then followed with them, in one go)
            self._follow(design)
            if fresh and self._background:
                self._copy_wake.set()

    def _follow(self, design: dict | None) -> None:
        """Follow `design` (None: the plugin's own layout) from now on, changing the stream when it's live. A good answer
        from Farmhand: any note that it couldn't be asked goes."""
        from .live_stream import chosen, stream  # (not at the top: the engine reads this module)
        from .store import session_factory, store

        db = store()
        before = chosen(db)
        with self._lock:
            self._design, self._error = design, None
            if design is None:
                self._got, self._wanted, self._copy_problem = None, None, None
        after = chosen(db)
        if not stream.status()["live"]:
            return
        if not after["enabled"]:  # let go, and the plugin's own switch is off: stopped, as turning it off does
            stream.stop()
            return
        if before["following"] != after["following"] or any(before[k] != after[k] for k in PICTURE_KEYS):
            self._send(db, session_factory)
        elif any(before[k] != after[k] for k in MUSIC_KEYS):
            stream.music_settings(after)

    def _send(self, db, session_factory) -> None:
        """The stream started again with what's followed now (a handover with no break)."""
        from .live_stream import stream

        try:
            stream.go_live(db, session_factory)
        except ValueError as e:  # (the design can't be sent: the stream carries on as it was)
            with self._lock:
                self._error = f"Stream control's layout can't be sent yet: {e}"

    # ------------------------------------------------------------------ the copier

    def _copy_rounds(self) -> None:
        while not self._stop.is_set():
            self._copy_wake.wait(POLL)
            self._copy_wake.clear()
            if self._stop.is_set():
                return
            try:
                self._copy_round()
            except Exception as e:  # noqa: BLE001 - a bad round must never end the copying
                print(f"stream: copying Stream control's files failed ({e})", flush=True)

    def _copy_round(self, send: bool = True) -> None:
        """Copy the newest list wanted (if any), then, while live and following, hand the stream over to the files when
        some changed (`send`: False when the design is followed straight after anyway)."""
        from .live_stream import stream
        from .store import session_factory, store

        with self._lock:
            wanted, self._wanted = self._wanted, None
        if wanted is None:
            return
        got, media = wanted

        def progress(done: int, of: int) -> None:
            with self._lock:
                self._progress = (done, of)

        try:
            problem, changed = self._copy_media(media, progress)
        finally:
            with self._lock:
                self._progress = None
        with self._lock:
            # (some files not copied: the next ask copies again, fetching only what's still missing)
            self._got = got if not problem else (*got, "again")
            self._copy_problem = problem
            following = self._design is not None
        if send and changed and following and stream.status()["live"]:
            self._send(store(), session_factory)

    # ------------------------------------------------------------------ the design's files

    def _folder(self) -> Path:
        return Path(config.settings.data_dir) / MEDIA_DIR

    def _copy_media(self, media: dict, progress=None) -> tuple[str | None, bool]:
        """Stream control's pictures, slideshows and music copied from Farmhand into the folder the stream reads while
        following (laid out as a stream folder: images/, slideshows/<name>/ with its order, music/). Only what's
        missing, or changed in Farmhand (its stamp, media.stamps, isn't the one last copied: STAMPS_FILE) is fetched,
        so a design saved again doesn't fetch every picture again; files no longer named are taken out. Farmhand asking
        it to slow down (429) is waited out and tried again. (What couldn't be copied, in a few words (None: all of it);
        whether any file was fetched or taken out.) `progress(done, of)` is told as each file is dealt with."""
        root = self._folder()
        client = farm.client(timeout=farm.QUICK)
        stamps = media.get("stamps") if isinstance(media.get("stamps"), dict) else {}
        had = _stamps_copied(root)
        copied: dict[str, str] = {}  # each file's stamp as copied now (or kept)
        failed: list[tuple[str, str]] = []  # (name, why)
        changed = [False]  # (any file fetched or taken out)
        count = [0, 0]  # (done, of)

        def fetch(path: str, rel: str, to: Path) -> None:
            try:
                _fetch(path, rel, to)
            finally:
                count[0] += 1
                if progress:
                    progress(count[0], count[1])

        def _fetch(path: str, rel: str, to: Path) -> None:
            stamp = stamps.get(rel)
            if to.is_file() and had.get(rel) == stamp:
                if stamp is not None:
                    copied[rel] = stamp
                return
            for attempt in range(BUSY_TRIES):
                try:
                    storage.write_bytes_atomically(to, client.file(path))
                except FarmhandError as e:
                    if e.kind == "busy" and attempt < BUSY_TRIES - 1:
                        time.sleep(min(BUSY_WAIT_MOST, e.retry_after or 1))
                        continue
                    failed.append((to.name, e.short))
                except OSError as e:
                    failed.append((to.name, str(e.strerror or e)))
                else:
                    changed[0] = True
                    if stamp is not None:
                        copied[rel] = stamp
                return

        def keep_only(d: Path, keep: set[str]) -> None:
            for f in d.iterdir() if d.is_dir() else []:
                if f.is_file() and f.name not in keep:
                    f.unlink(missing_ok=True)
                    changed[0] = True

        try:
            for d in (stream_media.IMAGES, stream_media.SLIDESHOWS, stream_media.MUSIC):
                (root / d).mkdir(parents=True, exist_ok=True)
            images = _media_names(media.get("images"), stream_media.PICTURE_TYPES)
            tracks = _media_names(media.get("music"), stream_media.TRACK_TYPES)
            count[1] = len(images) + len(tracks) + sum(
                len(_media_names(show.get("images"), stream_media.PICTURE_TYPES)) for show in media.get("slideshows") or []
                if isinstance(show, dict))
            for n in images:
                fetch(f"/stream/pictures/{_quote(n)}", f"{stream_media.IMAGES}/{n}", root / stream_media.IMAGES / n)
            keep_only(root / stream_media.IMAGES, set(images))

            shows = set()
            for show in media.get("slideshows") or []:
                try:
                    name = stream_media._name(show.get("name"), "slideshow")
                except (ValueError, TypeError, AttributeError):
                    continue
                shows.add(name)
                d = root / stream_media.SLIDESHOWS / name
                d.mkdir(exist_ok=True)
                pictures = _media_names(show.get("images"), stream_media.PICTURE_TYPES)
                for n in pictures:
                    fetch(f"/stream/slideshows/{_quote(name)}/pictures/{_quote(n)}", f"{stream_media.SLIDESHOWS}/{name}/{n}", d / n)
                keep_only(d, set(pictures) | {stream_media.ORDER_FILE})
                order = [n for n in show.get("images") or [] if n in pictures or stream_media.is_blank(n)]
                stream_media._write_order(d, order)  # (its blank screens live only in its order)
            for d in (root / stream_media.SLIDESHOWS).iterdir():
                if d.is_dir() and d.name not in shows:
                    keep_only(d, set())
                    changed[0] = True
                    try:
                        d.rmdir()
                    except OSError:
                        pass

            for n in tracks:
                fetch(f"/stream/music/{_quote(n)}", f"{stream_media.MUSIC}/{n}", root / stream_media.MUSIC / n)
            keep_only(root / stream_media.MUSIC, set(tracks))
            storage.write_text_atomically(root / STAMPS_FILE, json.dumps(copied, ensure_ascii=False))
        except OSError as e:
            return f"Stream control's pictures and music couldn't be copied into the plugin's folder ({root}): {e.strerror or e}", changed[0]
        return _not_copied(failed), changed[0]

follower = Follower()
