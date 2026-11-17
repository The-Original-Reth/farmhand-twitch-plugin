"""
Going live: every camera through its own feeder, to Twitch; a camera off, going live again after a restart, the
words falling back to names, and never Twitch while being tried out.
"""
from __future__ import annotations

import pytest

from streamer import config, farm, store
from streamer.live_stream import cameras, feeders, runner, stream

from .conftest import wait_until

from .conftest import KEY, grid

pytestmark = pytest.mark.usefixtures("stream_fresh")


# ------------------------------------------------------------------ going live


def test_going_live_reads_every_camera_through_its_own_feeder(api, ffmpeg, farmhand):
    grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: len(ffmpeg.commands) == 1 and len(ffmpeg.feeders) == 2)
    picture = ffmpeg.commands[0]
    assert "http://10.0.6.21/webcam/?action=stream" not in picture  # the picture never connects to a camera
    assert picture.count("image2pipe") == 2 and ffmpeg.senders[0][-1] == f"rtmps://ingest.global-contribute.live-video.net:443/app/{KEY}"
    assert wait_until(lambda: [x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]] == ["live", "live"])
    assert store.store().get(runner.LIVE_KEY) == "1"

    # a new layout: a new picture, the same feeders (no second connection to a camera)
    grid(api, [{"camera": "2:Camera"}, {"camera": "1:Bed"}, None, None], cols=2, rows=2)
    assert wait_until(lambda: len(ffmpeg.commands) == 2)
    assert len(ffmpeg.feeders) == 2 and len(ffmpeg.senders) == 1

    api.post("/api/stream/stop")
    assert store.store().get(runner.LIVE_KEY) is None
    assert wait_until(lambda: all(p.poll() is not None for p in ffmpeg.feeder_procs))


def test_going_live_with_a_camera_off_works_and_its_square_comes_back(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(feeders, "DOWN_AFTER", 0.3)
    monkeypatch.setattr(feeders, "RETRY_FIRST", 0.1)
    monkeypatch.setattr(feeders, "RETRY_MOST", 0.2)
    bed = "http://10.0.6.21/webcam/?action=stream"
    ffmpeg.down.add(bed)
    grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.post("/api/stream/start").status_code == 200

    def states():
        return {x["key"]: x["state"] for x in api.get("/api/stream").json()["status"]["camera_states"]}

    assert wait_until(lambda: states() == {"1:Bed": "down", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1  # the picture isn't started again for it
    ffmpeg.down.discard(bed)
    assert wait_until(lambda: states() == {"1:Bed": "live", "2:Camera": "live"})
    assert len(ffmpeg.commands) == 1


def test_it_goes_live_again_by_itself_after_a_restart(api, ffmpeg, farmhand, plugin):
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    stream.stop(forget=False)  # the container stopping
    assert plugin.get(runner.LIVE_KEY) == "1"

    farmhand.down = True  # (and Farmhand isn't even up: the cameras as last heard)
    restarted = store.Store(plugin.path)
    store.use(restarted)
    stream.resume(restarted, store.session_factory)
    assert wait_until(lambda: len(ffmpeg.commands) == 2 and stream.status()["live"])
    assert stream.status()["farmhand"] and "Can't reach Farmhand" in stream.status()["farmhand"]
    # Farmhand back (or taking the plugin again, after its address changed): the note goes as soon as it answers
    farmhand.down = False
    assert farm.print_of(1) is not None
    assert stream.status()["live"] and stream.status()["farmhand"] is None


def test_the_words_fall_back_to_the_printers_name_while_farmhand_is_down(api, ffmpeg, farmhand, monkeypatch):
    monkeypatch.setattr(cameras, "STATUS_EVERY", 0.2)
    grid(api, [{"camera": "1:Bed"}, None])
    api.post("/api/stream/start")
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    graph = ffmpeg.commands[0][ffmpeg.commands[0].index("-filter_complex") + 1]
    words = graph.split("textfile=")[1].split(":reload")[0].replace("\\:", ":")

    def said():
        try:
            return open(words, encoding="utf-8").read()
        except OSError:
            return ""

    assert wait_until(lambda: said() == "VT 1190 · Printing 42% · Frog.gcode")
    farmhand.down = True
    assert wait_until(lambda: said() == "VT 1190")
    assert stream.status()["live"]  # the stream carries on


def test_while_tried_out_the_stream_never_goes_to_twitch(api, ffmpeg, plugin, monkeypatch):
    monkeypatch.setattr(config.settings, "test_destination", "rtmp://127.0.0.1:1935/live")
    grid(api, [{"camera": "1:Bed"}, None])
    page = api.post("/api/stream/start").json()
    assert page["test_destination"] == "rtmp://127.0.0.1:1935/live"
    assert wait_until(lambda: len(ffmpeg.senders) == 1)
    assert ffmpeg.senders[0][-1] == f"rtmp://127.0.0.1:1935/live/{KEY}"


def test_going_live_needs_the_twitch_stream_key(api, ffmpeg, farmhand):
    grid(api, [{"camera": "1:Bed"}, None])
    api.put("/api/stream", json={"clear_key": True})
    r = api.post("/api/stream/start")
    assert r.status_code == 422 and "Twitch stream key" in r.json()["detail"]
    assert ffmpeg.senders == []


def test_the_volume_slider_is_heard_on_twitch_straight_away_without_being_saved(api, ffmpeg, farmhand, monkeypatch):
    """Moving the volume slider while live changes the music going out at once, not saved; leaving the page (or a page
    that stops saying so) puts the saved volume back."""
    monkeypatch.setattr(runner, "TRYING_FOR", 0.3)
    grid(api, [{"camera": "1:Bed"}, {"camera": "2:Camera"}])
    assert api.put("/api/stream", json={"music_volume": 30}).status_code == 200
    assert api.post("/api/stream/start").status_code == 200
    assert wait_until(lambda: runner.stream._player is not None)
    player = runner.stream._player

    assert api.post("/api/stream/music-volume", json={"volume": 80}).status_code == 200
    assert player.volume == 80 and api.get("/api/stream").json()["settings"]["music_volume"] == 30  # (not saved)
    assert api.post("/api/stream/music-volume", json={"volume": None}).status_code == 200
    assert player.volume == 30  # the page left: the saved volume

    api.post("/api/stream/music-volume", json={"volume": 70})
    assert player.volume == 70
    assert wait_until(lambda: player.volume == 30, timeout=3)  # not said again: back to the saved volume by itself

    api.post("/api/stream/music-volume", json={"volume": 60})
    assert api.put("/api/stream", json={"music_volume": 60}).status_code == 200  # saved: it stays
    assert player.volume == 60
    assert api.post("/api/stream/music-volume", json={"volume": 101}).status_code == 422
    api.post("/api/stream/stop")
