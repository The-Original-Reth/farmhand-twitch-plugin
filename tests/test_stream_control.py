"""
Farmhand's Stream control: while the plugin is ticked in it, its design is sent in place of the plugin's own layout
(which is kept, and comes back as soon as Stream control lets go), its files copied from Farmhand; and Farmhand starts
and stops the stream through /api/stream-control.
"""
from __future__ import annotations

import pytest

from streamer import config, store, stream_control, stream_media
from streamer.live_stream import chosen, settings

from .conftest import KEY, grid, wait_until

pytestmark = pytest.mark.usefixtures("stream_fresh")

OWN = [{"camera": "1:Bed"}, {"camera": "2:Camera"}]


def design(revision: int = 1, **changes) -> dict:
    """A design as Farmhand's GET /stream/design gives it."""
    return {
        "cols": 2, "rows": 1,
        "cells": [{"camera": "2:Camera"}, {"background": "#1F3A5F", "image": "logo.png", "text": "Live"}],
        "cameras": ["2:Camera"], "show_status": True, "layout": "grid", "seconds_all": 30, "seconds_each": 20,
        "resolution": "720p", "border_color": "#000000", "background": "#000000", "font": "play", "color": "#FFFFFF",
        "music": True, "music_volume": 50, "music_shuffle": True, "delay": 0,
        "holding": {"text": "Back soon", "image": None, "background": None, "color": None, "font": None},
        "title": "The print farm, live", "description": "", "revision": revision, "saved_at": "2026-11-17T18:00:00Z",
        **changes,
    }


@pytest.fixture()
def controlled(farmhand):
    """Stream control on, with this plugin ticked: a design with a picture, a slideshow (and a blank screen) and a track."""
    farmhand.design = design()
    farmhand.media = {"images": ["logo.png"], "slideshows": [{"name": "Finished prints", "images": ["blank:1", "frog.jpg"]}],
                      "music": ["beat.mp3"], "error": None}
    farmhand.files = {"pictures/logo.png": b"logo", "slideshows/Finished prints/pictures/frog.jpg": b"frog",
                      "music/beat.mp3": b"beat"}
    return farmhand


# (the stream's own tests fake ffmpeg: a card's picture would look like the holding screen to it, so live, a card of words)
WORDS = [{"camera": "2:Camera"}, {"background": "#1F3A5F", "text": "Live"}]


def pictures_of(command: list[str]) -> int:
    """How many cameras a picture ffmpeg reads."""
    return command.count("image2pipe")


def test_stream_controls_layout_takes_over_and_the_plugins_own_is_kept(api, controlled, plugin):
    grid(api, OWN)
    own = settings(plugin)
    stream_control.follower.check()

    sent = chosen(plugin)
    assert sent["following"] and sent["cameras"] == ["2:Camera"] and sent["cells"][1]["image"] == "logo.png"
    assert sent["title"] == "The print farm, live" and sent["delay"] == 0
    assert settings(plugin) == own  # the plugin's own layout, as it was
    assert api.get("/api/stream").json()["settings"]["cameras"] == ["1:Bed", "2:Camera"]

    # its files, copied from Farmhand where the stream reads them while following (the stream folder left alone)
    folder = config.settings.data_dir / stream_control.MEDIA_DIR
    assert stream_media.sent_picture_path(plugin, "logo.png").read_bytes() == b"logo"
    assert stream_media.sent_picture_path(plugin, "logo.png").parent == folder / "images"
    shown = stream_media.sent_slideshow_paths(plugin, "Finished prints")
    assert shown[0] == "blank:1" and shown[1].read_bytes() == b"frog"
    assert [p.name for p in stream_media.sent_track_paths(plugin)] == ["beat.mp3"]
    assert not list((config.settings.media_dir).rglob("logo.png"))

    page = api.get("/api/stream").json()
    assert page["stream_control"]["following"] is True and page["stream_control"]["revision"] == 1

    # a picture no longer listed is taken out of the copy
    controlled.media = {**controlled.media, "images": []}
    controlled.design = design(2)
    stream_control.follower.check()
    assert not (folder / "images" / "logo.png").exists()

    # Stream control switched off (or the plugin unticked): the plugin's own layout again
    controlled.design = None
    stream_control.follower.check()
    assert chosen(plugin)["following"] is False and chosen(plugin)["cameras"] == ["1:Bed", "2:Camera"]
    assert api.get("/api/stream").json()["stream_control"]["following"] is False


def test_not_following_without_the_permission_and_carrying_on_while_farmhand_is_down(api, controlled, plugin):
    stream_control.follower.check()
    assert stream_control.follower.following()
    controlled.down = True  # Farmhand restarting: carry on as it was
    stream_control.follower.check()
    assert stream_control.follower.following() and "Farmhand" in stream_control.follower.error()
    controlled.down = False
    controlled.permissions.discard("stream:read")  # 403: stream:read not granted
    stream_control.follower.check()
    assert not stream_control.follower.following()


def test_a_long_title_is_cut_to_twitchs(controlled, plugin):
    controlled.design = design(title="x" * 300)
    stream_control.follower.check()
    assert len(chosen(plugin)["title"]) == 140


def test_the_stream_follows_while_live(api, ffmpeg, controlled, plugin):
    grid(api, OWN)
    controlled.design = None
    stream_control.follower.check()
    r = api.post("/api/stream-control/start")
    assert r.status_code == 200 and r.json()["live"] is True and r.json()["following"] is False
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    assert pictures_of(ffmpeg.commands[0]) == 2

    # Stream control takes over: a new picture, with its one camera, handed over to with no new connection to Twitch
    controlled.design = design(1, cells=WORDS)
    stream_control.follower.check()
    assert wait_until(lambda: len(ffmpeg.commands) == 2)
    assert pictures_of(ffmpeg.commands[1]) == 1 and len(ffmpeg.senders) == 1
    assert api.get("/api/stream-control").json()["following"] is True

    # a new revision that changes the picture: the stream changes as a saved change does
    controlled.design = design(2, cells=WORDS, border_color="#FF0000")
    stream_control.follower.check()
    assert wait_until(lambda: len(ffmpeg.commands) == 3)

    # one that changes only the music: the music follows, the picture isn't made again
    controlled.design = design(3, cells=WORDS, border_color="#FF0000", music_volume=20)
    stream_control.follower.check()
    assert chosen(plugin)["music_volume"] == 20
    assert not wait_until(lambda: len(ffmpeg.commands) > 3, timeout=0.5)

    # a change saved on the plugin's own page while following: nothing sent changes
    assert api.put("/api/stream", json={"cols": 1, "rows": 1, "cells": [{"camera": "1:Bed"}]}).status_code == 200
    assert not wait_until(lambda: len(ffmpeg.commands) > 3, timeout=0.5)

    # let go: back to the plugin's own layout (as saved on its page meanwhile)
    controlled.design = None
    stream_control.follower.check()
    assert wait_until(lambda: len(ffmpeg.commands) == 4)
    assert pictures_of(ffmpeg.commands[3]) == 1 and "1:Bed" in chosen(plugin)["cameras"]

    r = api.post("/api/stream-control/stop")
    assert r.status_code == 200 and r.json()["live"] is False


def test_the_status_start_and_stop_routes(api, ffmpeg, controlled, plugin):
    controlled.design = design(cells=WORDS)
    r = api.get("/api/stream-control")
    assert r.json() == {"live": False, "following": False, "error": None, "watch_url": None}

    # no stream key yet: why not, in plain words
    r = api.post("/api/stream-control/start")
    assert r.status_code == 422 and "stream key" in r.json()["detail"]
    assert r.json()["detail"] and api.get("/api/stream-control").json()["following"] is True  # (asked on the way)

    api.put("/api/stream", json={"stream_key": KEY, "channel": "twitch.tv/PrintFarm"})
    r = api.post("/api/stream-control/start")
    assert r.status_code == 200, r.text
    assert r.json() == {"live": True, "following": True, "error": None, "watch_url": "https://www.twitch.tv/printfarm"}
    assert wait_until(lambda: len(ffmpeg.commands) == 1)
    assert pictures_of(ffmpeg.commands[0]) == 1
    assert store.store().get("live_wanted") == "1"

    r = api.post("/api/stream-control/stop")
    assert r.json()["live"] is False and store.store().get("live_wanted") is None
