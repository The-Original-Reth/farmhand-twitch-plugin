"""
The Twitch plugin's engine: printers' cameras sent live to Twitch, no OBS needed. Copied from the YouTube Stream
plugin (farmhand-youtube-plugin) and changed only where Twitch differs: where the stream goes, and no YouTube
sign-in or broadcast. Settings are in the plugin's own store, cameras and prints come from the plugin API, and each
camera is read by its own feeder (feeders.py).

The picture is a grid of squares, 1x1 to 5x5, on a background colour, each square holding a camera, a "card" or nothing,
in the order chosen, each with a border round it in the colour chosen. A card is a colour, with a picture or a slideshow
over it if you like, and words over that if you like; its pictures are files in the stream folder (stream_media.py).
Taking turns, the picture shows the whole grid for a while, then each camera on its own, round and round.

What's chosen is kept in the plugin's store (store.py); the pictures in the stream folder. The stream key is kept there
under a key of its own and never leaves the plugin again: it isn't returned by its API and is blanked out of anything
ffmpeg says.

Going live starts a feeder per camera (Farmhand gives each one's address), then the picture ffmpeg, which reads the
feeders' steady pipes (a camera that stops is a "Camera down" square), lays the squares out, writes each printer's
name and print under its camera, adds the music (the stream folder's MP3s, fed to ffmpeg as they play, music.py) or
a silent sound track (a stream needs one), and sends it all to the destination. If ffmpeg stops it is started again
after a short wait, for as long as the stream is meant to be live, and after the plugin's own restart too.
"""
from __future__ import annotations

# What the rest of the plugin uses. The package, file by file: constants (what the stream can be), fonts, squares (a
# square's choices, checked), choices (the stream's settings, kept and checked; twitch_choices the Twitch extras),
# sources (how ffmpeg reads each camera), frame (the picture's sizes), cards (a card's square), words (the words on the
# cameras), picture (the whole ffmpeg command), music (the music, fed to ffmpeg as it plays), encoders (processor or
# NVIDIA card), staging (the files going live puts out for ffmpeg), feeders (each camera's reader), down_square (its
# "Camera down" square), pump (the picture's steady camera pipes), layout_picture (a layout's picture made ready),
# holding (the holding screen), clips (what went to Twitch, kept for clips), runner (the stream itself).
from ..store import Store

from . import encoders, fonts, music, runner  # noqa: F401
from .choices import auto_grid, rename_slideshow, save, settings  # noqa: F401
from .constants import DESTINATIONS, RESOLUTION_LABELS, RESOLUTIONS, SETTINGS_KEY  # noqa: F401
from .fonts import DEFAULT_FONT, FONT, FONTS, font_file  # noqa: F401
from .picture import TURNS_FOR, Look, command, grid, timetable, windows  # noqa: F401
from .runner import stream  # noqa: F401
from .sources import Source, sources  # noqa: F401
from .squares import _camera_cell, _cell  # noqa: F401 (saved layouts use the same rules)
from .words import status_line  # noqa: F401

from .. import stream_media


def page(db: Store) -> dict:
    """Everything the Stream page shows: {settings, media (the stream folder's pictures, slideshows and music, stream_media.media),
    status, destinations, resolutions, fonts (what a square's words can be written in), test_destination (where
    the stream goes instead of Twitch while the plugin is being tried out, or None)}."""
    from .. import config

    return {
        "test_destination": config.settings.test_destination,
        "settings": settings(db),
        "media": stream_media.media(db),
        "status": stream.status(),
        "destinations": [{"key": k, "label": v["label"]} for k, v in DESTINATIONS.items()],
        "resolutions": [{"key": k, "label": RESOLUTION_LABELS[k]} for k in RESOLUTIONS],
        "fonts": [{"key": k, "label": v[0], "generic": v[2]} for k, v in FONTS.items()],
    }
