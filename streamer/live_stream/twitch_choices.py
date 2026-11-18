"""
The Twitch extras (the Twitch settings window): the stream title set from what the farm is printing (twitch_title.py),
chat commands answered by a bot, and Twitch chat shown on the stream. Kept with the stream's settings (choices.py) so
each has its place from the start. The title is built (READY); the chat ones aren't, and the page shows them greyed
out as coming later. The title's own wording is kept here too: title_format (while printing, with {prints} and {count})
and title_idle (when nothing is); "" for the plugin's own.
"""
from __future__ import annotations

from .constants import TWITCH_DEFAULTS

READY = {"title_from_printing": True, "chat_commands": False, "chat_on_screen": False}
EXTRAS_READY = all(READY.values())  # every extra built (none greyed out)
WORDING = ("title_format", "title_idle")
WORDING_MAX = 200


def kept(raw) -> dict:
    """The Twitch extras as kept (anything missing: off, or "")."""
    raw = raw if isinstance(raw, dict) else {}
    out = {name: raw.get(name) is True for name in TWITCH_DEFAULTS}
    for name in WORDING:
        out[name] = raw[name].strip()[:WORDING_MAX] if isinstance(raw.get(name), str) else ""
    return out


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
    for name in WORDING:
        if sent.get(name) is not None:
            if not isinstance(sent[name], str) or len(sent[name].strip()) > WORDING_MAX:
                raise ValueError(f"A title can be up to {WORDING_MAX} characters here (Twitch shows up to 140).")
            out[name] = sent[name].strip()
    return out
