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
"""
from __future__ import annotations

import copy
import json
import threading
import urllib.parse
from pathlib import Path

from . import config, farm, storage, stream_media
from .farmhand import FarmhandError

POLL = 5  # seconds between asking Farmhand for the design
MEDIA_DIR = "stream-control"  # in the plugin's own volume (DATA_DIR): Stream control's pictures and music, as a stream folder
PICTURE_KEYS = ("cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "border_color",
                "background", "font", "color")  # (as routes.PICTURE: these changed while live, the picture is made again)
MUSIC_KEYS = ("music", "music_volume", "music_shuffle")


def _quote(name: str) -> str:
    return urllib.parse.quote(name, safe="")


class Follower:
    def __init__(self):
        self._lock = threading.Lock()
        self._asking = threading.Lock()  # one ask at a time (the poll, and a Go live from Farmhand)
        self._design: dict | None = None  # Stream control's design while it's followed
        self._got: tuple | None = None  # (revision, media) of the files last copied in
        self._error: str | None = None
        # what couldn't be copied the last time the files were (kept while they're the same; never a note that Farmhand
        # couldn't be asked, which goes as soon as it answers again)
        self._copy_problem: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ what the rest of the plugin reads

    def design(self) -> dict | None:
        """Stream control's design while it's followed (a copy), else None (the plugin's own layout)."""
        with self._lock:
            return copy.deepcopy(self._design)

    def following(self) -> bool:
        with self._lock:
            return self._design is not None

    def error(self) -> str | None:
        with self._lock:
            return self._error

    def media_dir(self) -> Path | None:
        """Where Stream control's pictures and music are, while it's followed (laid out as the stream folder is)."""
        return self._folder() if self.following() else None

    def page(self) -> dict:
        """For the plugin's page: {following, revision, saved_at, title, error}."""
        with self._lock:
            d = self._design or {}
            return {"following": self._design is not None, "revision": d.get("revision"), "saved_at": d.get("saved_at"),
                    "title": d.get("title"), "error": self._error}

    # ------------------------------------------------------------------ asking Farmhand

    def start(self) -> None:
        """Ask every POLL seconds, in the background, until stop()."""
        self._stop.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="stream-control", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        """Back to the plugin's own layout, nothing asked yet (the tests' fresh start)."""
        with self._lock:
            self._design, self._got, self._error, self._copy_problem = None, None, None, None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check()
            except Exception as e:  # noqa: BLE001 - a bad answer must never end the asking
                print(f"stream: asking Stream control failed ({e})", flush=True)
            self._stop.wait(POLL)

    def check(self) -> None:
        """Ask Farmhand for the design once, follow what it says, and change the stream when that changes it."""
        with self._asking:
            try:
                answer = farm.client().stream_design()
            except FarmhandError as e:
                if e.status in (403, 404):  # stream:read not granted, or a Farmhand without Stream control
                    self._follow(None, None, None)
                else:  # Farmhand not answering: carry on as it was
                    with self._lock:
                        self._error = f"Couldn't ask Farmhand's Stream control: {e.short}"
                return
            if not isinstance(answer, dict) or answer.get("enabled") is not True or not isinstance(answer.get("design"), dict):
                self._follow(None, None, None)
                return
            design, media = answer["design"], answer.get("media") if isinstance(answer.get("media"), dict) else {}
            got = (design.get("revision"), json.dumps(media, sort_keys=True))
            with self._lock:
                fresh = got != self._got
            if fresh:
                problem = self._copy_media(media)
                with self._lock:
                    self._copy_problem = problem
            else:
                with self._lock:
                    problem = self._copy_problem
            self._follow(design, got, problem)

    def _follow(self, design: dict | None, got: tuple | None, problem: str | None) -> None:
        """Follow `design` (None: the plugin's own layout) from now on, changing the stream when it's live."""
        from .live_stream import chosen, stream  # (not at the top: the engine reads this module)
        from .store import session_factory, store

        db = store()
        before = chosen(db)
        with self._lock:
            media_changed = got is not None and self._got is not None and got[1] != self._got[1]
            self._design, self._got, self._error = design, got, problem
        after = chosen(db)
        if not stream.status()["live"]:
            return
        if before["following"] != after["following"] or media_changed or any(before[k] != after[k] for k in PICTURE_KEYS):
            try:
                stream.go_live(db, session_factory)
            except ValueError as e:  # (the design can't be sent: the stream carries on as it was)
                with self._lock:
                    self._error = f"Stream control's layout can't be sent yet: {e}"
        elif any(before[k] != after[k] for k in MUSIC_KEYS):
            stream.music_settings(after)

    # ------------------------------------------------------------------ the design's files

    def _folder(self) -> Path:
        return Path(config.settings.data_dir) / MEDIA_DIR

    def _copy_media(self, media: dict) -> str | None:
        """Stream control's pictures, slideshows and music copied from Farmhand into the folder the stream reads while
        following (laid out as a stream folder: images/, slideshows/<name>/ with its order, music/). Files no longer
        named are taken out. Pictures are copied each time (a picture replaced under its own name); a track only when
        it isn't there yet (MP3s are big). What couldn't be copied, in words (None: all of it)."""
        root = self._folder()
        client = farm.client(timeout=farm.QUICK)
        problems: list[str] = []

        def names(raw, types: dict) -> list[str]:
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

        def fetch(path: str, to: Path, again: bool = True) -> None:
            if not again and to.is_file():
                return
            try:
                storage.write_bytes_atomically(to, client.file(path))
            except FarmhandError as e:
                problems.append(f"{to.name}: {e.short}")
            except OSError as e:
                problems.append(f"{to.name}: {e.strerror or e}")

        def keep_only(d: Path, keep: set[str]) -> None:
            for f in d.iterdir() if d.is_dir() else []:
                if f.is_file() and f.name not in keep:
                    f.unlink(missing_ok=True)

        try:
            for d in (stream_media.IMAGES, stream_media.SLIDESHOWS, stream_media.MUSIC):
                (root / d).mkdir(parents=True, exist_ok=True)
            images = names(media.get("images"), stream_media.PICTURE_TYPES)
            for n in images:
                fetch(f"/stream/pictures/{_quote(n)}", root / stream_media.IMAGES / n)
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
                pictures = names(show.get("images"), stream_media.PICTURE_TYPES)
                for n in pictures:
                    fetch(f"/stream/slideshows/{_quote(name)}/pictures/{_quote(n)}", d / n)
                keep_only(d, set(pictures))
                order = [n for n in show.get("images") or [] if n in pictures or stream_media.is_blank(n)]
                stream_media._write_order(d, order)  # (its blank screens live only in its order)
            for d in (root / stream_media.SLIDESHOWS).iterdir():
                if d.is_dir() and d.name not in shows:
                    keep_only(d, set())
                    try:
                        d.rmdir()
                    except OSError:
                        pass

            tracks = names(media.get("music"), stream_media.TRACK_TYPES)
            for n in tracks:
                fetch(f"/stream/music/{_quote(n)}", root / stream_media.MUSIC / n, again=False)
            keep_only(root / stream_media.MUSIC, set(tracks))
        except OSError as e:
            problems.append(f"the plugin's folder for them ({root}): {e.strerror or e}")
        if not problems:
            return None
        more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
        return "Some of Stream control's pictures or music couldn't be copied from Farmhand: " + "; ".join(problems[:3]) + more


follower = Follower()
