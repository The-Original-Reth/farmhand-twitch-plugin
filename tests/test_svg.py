"""
SVG pictures: uploaded and shown on the page like any other, and drawn as PNGs for the stream (live_stream/svg.py), since
ffmpeg's loop and Pillow read PNG, JPEG and WebP only.
"""
from __future__ import annotations

import subprocess

import pytest

from PIL import Image

from streamer.live_stream import svg

LOGO = b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><rect width="20" height="10" fill="#00f"/></svg>'


@pytest.fixture()
def drawn(monkeypatch):
    """svg.render as Pillow: a 200x100 blue PNG for each SVG (the real one is the image's ffmpeg, with librsvg)."""
    calls = []

    def render(src, to, width=svg.WIDTH):
        calls.append(src)
        Image.new("RGBA", (200, 100), (0, 0, 255, 255)).save(to, "PNG")

    monkeypatch.setattr(svg, "render", render)
    return calls


def test_an_svg_is_uploaded_and_shown_on_the_page_without_running_anything_in_it(api, plugin, tmp_path):
    r = api.post("/api/stream/pictures", files={"files": ("logo.svg", LOGO, "image/svg+xml")})
    assert r.status_code == 201 and r.json()["media"]["images"] == ["logo.svg"]
    assert (tmp_path / "media" / "images" / "logo.svg").read_bytes() == LOGO
    r = api.get("/api/stream/pictures/logo.svg")
    assert r.status_code == 200 and r.content == LOGO and r.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in r.headers["content-security-policy"] and "script" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in api.get("/api/stream/pictures/logo.svg".replace(".svg", ".png")).headers
    r = api.post("/api/stream/slideshows/Logos/pictures", files={"files": ("a.svg", LOGO, "image/svg+xml")})
    assert r.status_code == 201
    assert "sandbox" in api.get("/api/stream/slideshows/Logos/pictures/a.svg").headers["content-security-policy"]
    r = api.post("/api/stream/pictures", files={"files": ("logo.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422 and "PNG, JPEG, WebP or SVG" in r.json()["detail"]


def test_an_svg_is_drawn_as_a_png_for_the_stream_and_others_are_copied(tmp_path, drawn):
    from streamer.live_stream import staging

    src = tmp_path / "src"
    src.mkdir()
    (src / "logo.svg").write_bytes(LOGO)
    Image.new("RGB", (4, 4)).save(src / "photo.png")
    out = staging.local_copies({0: [str(src / "logo.svg"), str(src / "photo.png")], 1: [str(src / "logo.svg")]},
                               str(tmp_path / "live"))
    assert out[0][0].endswith("logo.svg.png") and out[0][1].endswith("photo.png") and out[1] == [out[0][0]]
    with Image.open(out[0][0]) as im:
        assert im.format == "PNG" and im.size == (200, 100)
    assert drawn == [str(src / "logo.svg")]  # (one SVG in two squares: drawn once)


def test_an_svg_ffmpeg_cant_draw_is_left_out(tmp_path, monkeypatch):
    from streamer.live_stream import procs, staging

    (tmp_path / "bad.svg").write_bytes(b"<svg")
    monkeypatch.setattr(procs, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    asked = []

    def run(args, **kw):
        asked.append(args)
        return subprocess.CompletedProcess(args, 1, "", "Error parsing svg!\n")

    monkeypatch.setattr(subprocess, "run", run)
    assert staging.local_copies({0: [str(tmp_path / "bad.svg")]}, str(tmp_path / "live")) == {0: []}
    args = asked[0]
    assert args[args.index("-width") + 1] == "1920" and args[args.index("-height") + 1] == "1920" and args[args.index("-i") + 1] == str(tmp_path / "bad.svg")
    with pytest.raises(OSError, match="Error parsing svg"):
        svg.render(str(tmp_path / "bad.svg"), str(tmp_path / "x.png"))
    monkeypatch.setattr(procs, "ffmpeg_path", lambda: None)
    with pytest.raises(OSError, match="ffmpeg"):
        svg.render(str(tmp_path / "bad.svg"), str(tmp_path / "x.png"))


def test_the_holding_screen_shows_an_svg_picture(api, plugin, ffmpeg, tmp_path, drawn):
    from streamer import store
    from streamer.live_stream import holding

    api.post("/api/stream/pictures", files={"files": ("logo.svg", LOGO, "image/svg+xml")})
    api.put("/api/stream", json={"holding": {"image": "logo.svg", "background": "#000000"}})
    from streamer import live_stream
    chosen = live_stream.settings(store.store())
    folder = tmp_path / "hold"
    folder.mkdir()
    assert holding.start(store.store(), chosen, "/usr/bin/ffmpeg", str(folder)) is not None
    assert drawn and (folder / "holding-picture.png").is_file()
    with Image.open(folder / "holding.png") as im:
        im = im.convert("RGB")
        assert (0, 0, 255) in {im.getpixel((x, y)) for y in range(0, im.height, 8) for x in range(0, im.width, 8)}


def test_an_svgs_shape_is_read_from_its_size_or_its_viewbox():
    def sized(attrs):
        return svg.size(f'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" {attrs}><rect/></svg>'.encode())

    assert sized('width="20" height="10"') == (1920, 960)
    assert sized("width='20mm' height='40mm' viewBox='0 0 1 1'") == (960, 1920)  # (its size first)
    assert sized('viewBox="0 0 300 100"') == (1920, 640)  # only a viewBox: librsvg alone would draw it 100 high
    assert sized('width="100%" height="50%" viewBox="0,0,16,9"') == (1920, 1080)  # (no size in one unit: the viewBox)
    assert sized('width="20px" height="10"') == (1920, 1920)  # (units that differ and no viewBox: square)
    assert svg.size(b"not an svg") == (1920, 1920)
    assert svg.size(b'<svg viewBox="0 0 1 1000"/>') == (2, 1920)
