"""
The stream when things go wrong at the wrong moment: Stop pressed while a new layout is on its way, a connection to
Twitch that silently stops taking anything, an ffmpeg that can't be started, and a layout's folder after a hand-over.
"""
from __future__ import annotations

import os
import threading
import time

import pytest

from streamer import farm, store
from streamer.live_stream import pictures, runner, self_check, sending, stream

from .conftest import grid, wait_until

pytestmark = pytest.mark.usefixtures("stream_fresh")


def _slow_cameras(monkeypatch):
    """Farmhand slow to answer for the cameras: go_live waits in farm.cameras until `release` is set."""
    asked, release = threading.Event(), threading.Event()
    real = farm.cameras

    def slow(db):
        asked.set()
        release.wait(5)
        return real(db)

    monkeypatch.setattr(farm, "cameras", slow)
    return asked, release


def _go_live_in_background():
    done = threading.Event()

    def run():
        try:
            stream.go_live(store.store(), store.session_factory)
        finally:
            done.set()

    threading.Thread(target=run, daemon=True).start()
    return done


# ------------------------------------------------------------------ Stop always wins


def test_stop_pressed_while_a_new_layout_waits_for_farmhand_stays_stopped(api, ffmpeg, farmhand, plugin, monkeypatch):
    """A new layout asks Farmhand for the cameras (up to 20 s); Stop pressed meanwhile used to be undone: the layout
    found the stream not live, started it afresh and remembered it as live, so it came back after every restart too."""
    grid(api, [{"camera": "1:Bed"}, None])
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: len(ffmpeg.commands) == 1 and len(ffmpeg.senders) == 1)

    asked, release = _slow_cameras(monkeypatch)
    done = _go_live_in_background()  # (as a new layout saved, or Stream control's, does while live)
    assert asked.wait(5)
    began = time.monotonic()
    assert api.post("/api/stream/stop").status_code == 200
    assert time.monotonic() - began < 2  # (Stop doesn't wait for Farmhand)
    release.set()
    assert done.wait(5)
    time.sleep(0.3)

    assert not stream.status()["live"] and plugin.get(runner.LIVE_KEY) is None
    assert len(ffmpeg.senders) == 1 and all(p.poll() is not None for p in ffmpeg.sender_procs)  # (no new connection)
    assert len(ffmpeg.commands) == 1 and all(p.poll() is not None for p in ffmpeg.procs)
    assert wait_until(lambda: all(p.poll() is not None for p in ffmpeg.feeder_procs))


def test_stop_pressed_while_going_live_waits_for_farmhand_stays_stopped(api, ffmpeg, farmhand, plugin, monkeypatch):
    grid(api, [{"camera": "1:Bed"}, None])
    asked, release = _slow_cameras(monkeypatch)
    done = _go_live_in_background()
    assert asked.wait(5)
    stream.stop()
    release.set()
    assert done.wait(5)
    time.sleep(0.3)
    assert not stream.status()["live"] and plugin.get(runner.LIVE_KEY) is None
    assert ffmpeg.senders == [] and ffmpeg.commands == [] and ffmpeg.feeders == []


def test_go_live_after_stop_still_works(api, ffmpeg, farmhand, plugin):
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    api.post("/api/stream/stop")
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: stream.status()["on_air"]) and plugin.get(runner.LIVE_KEY) == "1"


# ------------------------------------------------------------------ what actually reaches Twitch


class _NotTaking:
    """A sender's stdin whose connection to Twitch has stopped taking anything: a write waits until its ffmpeg ends."""

    def __init__(self, proc):
        self.proc = proc

    def write(self, data):
        while self.proc.poll() is None:
            time.sleep(0.02)
        raise BrokenPipeError("the sender ended")

    def flush(self):
        pass


def test_a_sender_that_stops_taking_anything_is_not_on_air_and_is_connected_again(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(runner, "NOT_TAKING", 0.2)
    monkeypatch.setattr(self_check, "CHECK_EVERY", 0.05)
    monkeypatch.setattr(self_check, "STALL", 1000)  # (the picture's own check kept out of it)
    monkeypatch.setattr(self_check, "SENDER_STALL", 0.6)
    monkeypatch.setattr(sending, "RETRY_SECONDS", 0.1)
    grid(api, [{"camera": "1:Bed"}, None])
    api.put("/api/stream", json={"delay": 0})
    api.post("/api/stream/start")
    assert wait_until(lambda: stream.status()["on_air"])
    sender = ffmpeg.sender_procs[0]
    assert "-rw_timeout" in ffmpeg.senders[0]  # (ffmpeg gives up on a dead connection by itself, too)

    stream._buffer.set_sink(_NotTaking(sender))  # the network goes quiet: ffmpeg runs on, taking nothing
    stream._buffer.write(b"\x47" + bytes(187))
    assert wait_until(lambda: not stream.status()["on_air"], timeout=3)
    assert sender.poll() is None and stream.status()["live"]  # (still running: only what it takes shows it)

    assert wait_until(lambda: sender.poll() is not None, timeout=3)  # the self-check ends it...
    assert wait_until(lambda: len(ffmpeg.senders) == 2, timeout=3)  # ...and it's connected again
    status = stream.status()
    assert "Twitch took nothing from the stream" in status["self_check"]["message"]
    assert wait_until(lambda: stream.status()["on_air"], timeout=3)


# ------------------------------------------------------------------ an ffmpeg that can't be started


def _failing_first(ffmpeg, kind):
    """popen that raises OSError the first time it's asked for `kind` ("sender" or "picture")."""
    failed = []

    def popen(args, feed=False, out=False):
        is_picture = "-filter_complex" in args
        is_sender = args[-1].startswith("rtmp") and not is_picture
        if not failed and ((kind == "picture" and is_picture) or (kind == "sender" and is_sender)):
            failed.append(args)
            raise OSError(12, "Cannot allocate memory")
        return ffmpeg(args, feed=feed, out=out)

    return popen, failed


def test_a_sender_that_cant_be_started_is_tried_again(api, ffmpeg, farmhand, plugin, monkeypatch):
    from streamer.live_stream import procs

    popen, failed = _failing_first(ffmpeg, "sender")
    monkeypatch.setattr(procs, "popen", popen)
    monkeypatch.setattr(sending, "RETRY_SECONDS", 0.2)
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: failed, timeout=3)
    assert stream.status()["live"]  # (it used to stop wanting to be live there, leaving everything else running)
    assert wait_until(lambda: len(ffmpeg.senders) == 1 and stream.status()["on_air"], timeout=3)
    stream.stop()
    assert plugin.get(runner.LIVE_KEY) is None and all(p.poll() is not None for p in ffmpeg.procs + ffmpeg.sender_procs)


def test_a_picture_that_cant_be_started_is_tried_again(api, ffmpeg, farmhand, monkeypatch):
    from streamer.live_stream import procs

    popen, failed = _failing_first(ffmpeg, "picture")
    monkeypatch.setattr(procs, "popen", popen)
    monkeypatch.setattr(pictures, "RETRY_SECONDS", 0.2)
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: failed, timeout=3)
    assert wait_until(lambda: len(ffmpeg.commands) == 1 and stream.status()["on_air"], timeout=3)


# ------------------------------------------------------------------ a layout's folder


def test_the_old_layouts_folder_goes_once_a_new_layout_takes_over(api, ffmpeg, farmhand):
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: stream.status()["on_air"] and stream._dir)
    first = stream._dir
    assert os.path.isdir(first)
    grid(api, [None, {"camera": "1:Bed"}])
    assert wait_until(lambda: stream._dir not in (None, first), timeout=5)
    assert wait_until(lambda: not os.path.exists(first), timeout=5)
    assert os.path.isdir(stream._dir)  # (the new one's kept while it's going out)
