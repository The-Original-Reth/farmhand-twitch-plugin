"""
SVG pictures, drawn as PNGs for the stream: ffmpeg (as a loop) and Pillow (slides, the holding screen) read PNG, JPEG and
WebP, never SVG. The image's ffmpeg draws an SVG itself (Debian's is built with librsvg), so no other library is needed:
it's drawn WIDTH on its longer side, its own shape kept and its see-through parts left see-through, then fitted where it
goes like any other picture. Its shape is read here (librsvg makes one with only a viewBox 100 high, squashed).
"""
from __future__ import annotations

import os
import re
import subprocess

from . import procs

WIDTH = 1920  # its longer side: enough for a picture filling the whole stream at its largest size
TIMEOUT = 30

_ROOT = re.compile(rb"<svg\b([^>]*)>", re.I)
_NUMBER = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:e[-+]?[0-9]+)?)\s*([a-z]*)\s*$", re.I)


def is_svg(path: str) -> bool:
    return str(path).lower().endswith(".svg")


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf"(?:^|\s){name}\s*=\s*([\"'])(.*?)\1", tag, re.S)
    return m.group(2) if m else None


def shape(data: bytes) -> float:
    """An SVG's width over its height: from its width and height (both in the same unit, not %), else its viewBox, else
    square."""
    m = _ROOT.search(data[:65536])
    tag = m.group(1).decode("utf-8", "replace") if m else ""
    w, h = (_NUMBER.match(_attr(tag, a) or "") for a in ("width", "height"))
    if w and h and w.group(2).lower() == h.group(2).lower() and float(w.group(1)) > 0 and float(h.group(1)) > 0:
        return float(w.group(1)) / float(h.group(1))
    box = (_attr(tag, "viewBox") or "").replace(",", " ").split()
    try:
        bw, bh = float(box[2]), float(box[3])
        if bw > 0 and bh > 0:
            return bw / bh
    except (IndexError, ValueError):
        pass
    return 1.0


def size(data: bytes, longest: int = WIDTH) -> tuple[int, int]:
    """The size an SVG is drawn at: `longest` on its longer side, its shape kept (each side at least 1)."""
    ratio = shape(data)
    if ratio >= 1:
        return longest, max(1, round(longest / ratio))
    return max(1, round(longest * ratio)), longest


def render(src: str, to: str, width: int = WIDTH) -> None:
    """The SVG at `src` drawn as a PNG at `to` (swapped in whole), `width` on its longer side. OSError when it can't be
    (no ffmpeg, or an SVG ffmpeg can't read): the picture is then left out, as an unreadable one is."""
    with open(src, "rb") as f:
        w, h = size(f.read(65536), width)
    ffmpeg = procs.ffmpeg_path()
    if not ffmpeg:
        raise OSError("ffmpeg isn't there to draw the SVG")
    tmp = to + ".new.png"
    try:
        done = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-y", "-width", str(w), "-height", str(h), "-keep_ar", "0",
                               "-i", src, "-frames:v", "1", "-update", "1", tmp], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise OSError(f"drawing {os.path.basename(src)} took too long") from e
    if done.returncode or not os.path.isfile(tmp):
        said = (done.stderr or "").strip().splitlines()
        raise OSError(f"{os.path.basename(src)} couldn't be drawn ({said[-1] if said else 'ffmpeg gave no picture'})")
    os.replace(tmp, to)


def copy_for_stream(src: str, to: str, copy) -> str:
    """`src` put at `to` for the stream: copied (with `copy`), or an SVG drawn as `to`.png. The path it's at."""
    if is_svg(src):
        to += ".png"
        render(src, to)
    else:
        copy(src, to)
    return to
