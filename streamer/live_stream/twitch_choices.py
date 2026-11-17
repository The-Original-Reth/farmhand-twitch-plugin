"""
The Twitch extras (the Twitch settings window): the stream title set from what the farm is printing, chat commands
answered by a bot, and Twitch chat shown on the stream. Kept with the stream's settings (choices.py) so each has its
place from the start; none of them does anything yet, and the page shows them as coming later (EXTRAS_READY).
"""
from __future__ import annotations

from .constants import TWITCH_DEFAULTS

EXTRAS_READY = False  # True once the extras below are built: until then the page shows them greyed out


def kept(raw) -> dict:
    """The Twitch extras as kept (anything missing: off)."""
    raw = raw if isinstance(raw, dict) else {}
    return {name: raw.get(name) is True for name in TWITCH_DEFAULTS}


def checked(sent, now: dict) -> dict:
    """The Twitch extras as sent (only what's sent changes): ValueError says what's wrong."""
    if not isinstance(sent, dict):
        raise ValueError("The Twitch settings didn't come through.")
    out = dict(now)
    for name in TWITCH_DEFAULTS:
        if sent.get(name) is not None:
            if sent[name] and not EXTRAS_READY:
                raise ValueError("That Twitch extra isn't ready yet: it comes in a later version of the plugin.")
            out[name] = bool(sent[name])
    return out
