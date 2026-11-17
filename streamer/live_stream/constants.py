"""
What the stream can be: where it goes, its sizes, its limits and timings, and how its settings are kept.
"""
from __future__ import annotations

import re

SETTINGS_KEY = "live_stream"  # see settings()
STREAM_KEY_KEY = "live_stream_key"  # the stream key itself, on its own

# Where the stream goes: Twitch's global ingest over RTMPS (it picks the nearest Twitch server), the stream key goes on
# the end. This plugin is for Twitch only (YouTube is the YouTube Stream plugin, a container of its own).
DESTINATIONS = {
    "twitch": {"label": "Twitch", "url": "rtmps://ingest.global-contribute.live-video.net:443/app/"},
}
DEFAULT_DESTINATION = "twitch"
KEY_SHAPE = re.compile(r"^[A-Za-z0-9_\-?=&.]{4,200}$")
MAX_SIDE = 5  # the grid is 1x1 to 5x5
MAX_CAMERAS = MAX_SIDE * MAX_SIDE
CAMERA_KEY = re.compile(r"^\d+:.{1,100}$")  # "printer id:camera name", as Monitor names them

FPS = 15
# The picture's camera pipes and its sound are written at the pace they play, and the picture ffmpeg counts its time in
# frames and samples: time a writer falls behind (the picture ffmpeg stopped reading for a moment) is made up, not
# skipped, or the picture's clock falls behind the real one and the sender empties the stream delay to keep up. Up to
# this many seconds; more is a real gap (the self-check sees to a stream that has stopped).
CATCH_UP_MOST = 120
STEADY_AFTER = 2  # seconds of it a reader has taken before it counts as reading (until then, nothing is made up)
# The sizes the stream can be sent at: (width, height, video bitrate), and their names. Twitch takes up to 1080p and
# 6000 kbit/s; at 15 frames a second these are plenty, and leave room for viewers on slower connections.
RESOLUTIONS = {
    "720p": (1280, 720, 2500),
    "1080p": (1920, 1080, 3500),
}
RESOLUTION_LABELS = {"720p": "720p (1280×720)", "1080p": "1080p (1920×1080)"}
DEFAULT_RESOLUTION = "720p"
WIDTH, HEIGHT, _ = RESOLUTIONS[DEFAULT_RESOLUTION]
RETRY_SECONDS = 10  # how long after ffmpeg stops it is started again
STATUS_EVERY = 15  # how often the print progress written on the video is brought up to date
KEPT_LINES = 30  # how much of what ffmpeg said is kept, to say why it stopped

LAYOUTS = ("grid", "cycle")  # the grid all the time, or taking turns
SECONDS = {"seconds_all": (0, 3600, 30), "seconds_each": (3, 3600, 20)}  # (least, most, default); seconds_all 0: never
DEFAULT_BORDER = "#000000"
DEFAULT_BACKGROUND = "#000000"  # the stream's own colour: empty squares, and round anything that doesn't fill its square
BORDER_WIDTH = 3  # px round each square, on the 720-high picture
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_TEXT_COLOR = "#FFFFFF"  # the stream's words, unless a square has its own
# The Twitch extras (the Twitch settings window), all off until they're built (twitch_choices.py)
TWITCH_DEFAULTS = {"title_from_printing": False, "chat_commands": False, "chat_on_screen": False}
DELAY = (0, 120, 60)  # (least, most, default) seconds the stream is held before Twitch gets it (relay.Buffer)
DEFAULT_MUSIC_VOLUME = 50  # the music's loudness, 0 to 100 (100: as the tracks are)
SAVED = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "font", "color", "enabled",
         "resolution", "border_color", "background", "music", "music_volume", "music_shuffle", "delay", "twitch", "holding")
# The holding screen: what Twitch is shown for the first minute after the plugin's own restart, while the delay fills
# again behind it (so the channel never goes without video). Its words, a picture from the stream folder's images (None:
# none), and its colours and font (None: the stream's own).
HOLDING_DEFAULTS = {"text": "Back in a minute", "image": None, "background": None, "color": None, "font": None}
HOLDING_TEXT_MAX = 300
