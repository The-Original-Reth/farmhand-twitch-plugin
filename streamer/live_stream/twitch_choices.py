"""
The Twitch extras (the Twitch settings window): the stream title set from what the farm is printing, chat commands
answered by a bot, and Twitch chat shown on the stream. Kept with the stream's settings (choices.py) so each has its
place from the start; none is built yet (READY), and the page shows them greyed out as coming later. (The stream's
title on Twitch is Stream control's, while it's followed: twitch_title.py, not an extra.)
"""
from __future__ import annotations

from .constants import TWITCH_DEFAULTS

READY = {"title_from_printing": False, "chat_commands": False, "chat_on_screen": False}
EXTRAS_READY = all(READY.values())  # every extra built (none greyed out)


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
            if sent[name] and not READY.get(name):
                raise ValueError("That Twitch extra isn't ready yet: it comes in a later version of the plugin.")
            out[name] = bool(sent[name])
    return out
