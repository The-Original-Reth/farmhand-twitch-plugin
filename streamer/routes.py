from __future__ import annotations

import os

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from . import live_stream, storage, stream_control, stream_media, twitch_title
from .errors import answer_errors
from .schemas import SlideshowIn, SlideshowOrderIn, StreamSettingsIn
from .store import Store, session_factory, store


def get_db() -> Store:
    """Every route's `db`: the plugin's store (store.py)."""
    return store()


def require_confirm(confirm: bool) -> None:
    """A delete must say confirm=true (as on Farmhand's API): the page's own question is the real guard."""
    if not confirm:
        raise HTTPException(status_code=409, detail="Deleting needs confirm=true.")

# The Stream page's API (as in the YouTube Stream plugin it was copied from), under the plugin's /api/stream: printers' cameras sent
# live to Twitch (see live_stream/). The stream key goes in and never comes back out: answers only say it's there. (Where the stream folder is isn't chosen
# here: it's the folder the plugin's container is given.)
router = APIRouter(prefix="/api/stream", tags=["stream"])

# Changing one of these while live means the picture (or the sound) changes, so the stream starts again. (Not the
# resolution: the size going out is set when going live, and a new one saved while live waits for the next Go live.)
PICTURE = ("destination", "cols", "rows", "cells", "show_status", "layout", "seconds_all", "seconds_each", "border_color",
           "background", "font", "color", "key_set")
MUSIC = ("music", "music_volume", "music_shuffle")  # these the music follows while live, without starting it again


def _restart_if_live(db: Store) -> None:
    if live_stream.stream.status()["live"]:
        live_stream.stream.go_live(db, session_factory)


@router.get("")
def stream_page(db: Store = Depends(get_db)):
    """{settings, media, status, destinations, resolutions, fonts}: see live_stream.page."""
    return live_stream.page(db)


@router.put("")
def save_settings(payload: StreamSettingsIn, db: Store = Depends(get_db)):
    """
    Save the stream's settings. While live: a change to the picture starts the stream again with it; turning the
    stream off (enabled: false) stops it.
    """
    with answer_errors():
        before = live_stream.chosen(db)  # (what the stream sends: while Stream control is followed, its layout is, not this)
        live_stream.save(
            db, destination=payload.destination, chosen=payload.cameras, show_status=payload.show_status, layout=payload.layout,
            seconds_all=payload.seconds_all, seconds_each=payload.seconds_each, resolution=payload.resolution,
            border_color=payload.border_color, background=payload.background, font=payload.font, color=payload.color, enabled=payload.enabled, cols=payload.cols, rows=payload.rows, cells=payload.cells,
            music=payload.music, music_volume=payload.music_volume, music_shuffle=payload.music_shuffle, delay=payload.delay, twitch=payload.twitch, channel=payload.channel, holding=payload.holding,
            stream_key=payload.stream_key, clear_key=payload.clear_key,
        )
        after = live_stream.chosen(db)
        live = live_stream.stream.status()["live"]
        if live and not after["enabled"]:  # turned off: nothing streams
            live_stream.stream.stop()
        elif live and (any(before[k] != after[k] for k in PICTURE) or payload.stream_key):
            _restart_if_live(db)
        elif live and any(before[k] != after[k] for k in MUSIC):
            live_stream.stream.music_settings(after)
    if payload.twitch is not None:
        twitch_title.keeper.forget_title()  # (its wording may have changed: sent again)
        twitch_title.keeper.poke()
    return live_stream.page(db)


@router.post("/start")
def go_live(db: Store = Depends(get_db)):
    """Go live with what's saved. 422 says why not (no key, no cameras, a camera that can't be streamed...)."""
    with answer_errors():
        live_stream.stream.go_live(db, session_factory)
    twitch_title.keeper.poke()  # (the title set as the stream goes live)
    return live_stream.page(db)


@router.post("/stop")
def stop(db: Store = Depends(get_db)):
    live_stream.stream.stop()
    return live_stream.page(db)


# ------------------------------------------------------------------ the stream folder: pictures and slideshows


def _media(call):
    """A stream folder request: its errors as answers (503 while the folder isn't available)."""
    try:
        with answer_errors():
            return call()
    except storage.StorageUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None


def _restart_if_used(db: Store, slideshow: str | None, image: str | None = None) -> None:
    """Pictures changed: the stream starts again with them, when it's live and a square shows them. (Not while Stream
    control is followed: the stream shows its pictures then, not the stream folder's.)"""
    if stream_control.follower.following():
        return
    def on_it(c) -> bool:  # (its own picture, or one of its more pictures, a slideshow screen's too)
        layers = [*(c.get("layers") or []), *(x for ls in (c.get("slide_layers") or {}).values() for x in ls)]
        return c.get("image") == image or any(x.get("type") == "picture" and x.get("image") == image for x in layers)

    for c in live_stream.settings(db)["cells"]:
        if c and "camera" not in c and ((slideshow and c.get("slideshow") == slideshow) or (image and on_it(c))):
            _restart_if_live(db)
            return


# An SVG can carry scripts: opened on its own it would run them as this page. It's sent as a picture that can't
# (CSP sandbox, no scripts), as an <img> shows it anyway.
SVG_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox",
               "X-Content-Type-Options": "nosniff"}


def _picture_answer(data: bytes, kind: str) -> Response:
    headers = {"Cache-Control": "no-cache", **(SVG_HEADERS if kind == "image/svg+xml" else {})}
    return Response(content=data, media_type=kind, headers=headers)


@router.get("/pictures/{name}")
def get_picture(name: str, db: Store = Depends(get_db)):
    return _picture_answer(*_media(lambda: stream_media.picture(db, None, name)))


@router.post("/pictures", status_code=201)
async def add_pictures(files: list[UploadFile] = File(...), db: Store = Depends(get_db)):
    """Pictures (PNG, JPEG, WebP or SVG, under 10 MB each) into the stream folder's images. Answers the page."""
    for file in files:
        data = await file.read(stream_media.PICTURE_MAX + 1)
        _media(lambda: stream_media.add_picture(db, None, file.filename or "", data))
    return live_stream.page(db)


@router.delete("/pictures/{name}")
def delete_picture(name: str, confirm: bool = Query(False), db: Store = Depends(get_db)):
    """Delete a picture from the stream folder. Squares showing it keep their colour and words."""
    require_confirm(confirm)
    _media(lambda: stream_media.remove_picture(db, None, name))
    _restart_if_used(db, None, name)
    return live_stream.page(db)


@router.post("/slideshows", status_code=201)
def add_slideshow(payload: SlideshowIn, db: Store = Depends(get_db)):
    """A new, empty slideshow: a folder of that name in the stream folder's slideshows. Answers the page."""
    _media(lambda: stream_media.add_slideshow(db, payload.name))
    return live_stream.page(db)


@router.put("/slideshows/{name}")
def rename_slideshow(name: str, payload: SlideshowIn, db: Store = Depends(get_db)):
    """Rename a slideshow: its folder in the stream folder, and every square showing it (on the page and in saved
    layouts) follows. 422 for a name another slideshow has. While live and it's shown, the stream starts again."""
    new = _media(lambda: stream_media.rename_slideshow(db, name, payload.name))
    if new != name and live_stream.rename_slideshow(db, name, new):
        _restart_if_used(db, new)
    return live_stream.page(db)


@router.post("/slideshows/{name}/blanks", status_code=201)
def add_blank(name: str, db: Store = Depends(get_db)):
    """A blank screen at the end of a slideshow (its colour and the words written on it). Deleted as its pictures are."""
    _media(lambda: stream_media.add_blank(db, name))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.put("/slideshows/{name}/order")
def order_slideshow(name: str, payload: SlideshowOrderIn, db: Store = Depends(get_db)):
    """Put a slideshow's pictures in the order chosen (kept in its folder). While live and it's shown, the stream starts again."""
    _media(lambda: stream_media.set_order(db, name, payload.order))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.delete("/slideshows/{name}")
def delete_slideshow(name: str, confirm: bool = Query(False), db: Store = Depends(get_db)):
    """Delete a slideshow: its pictures, then its folder (left when it holds anything else). Squares keep their colour."""
    require_confirm(confirm)
    _media(lambda: stream_media.remove_slideshow(db, name))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.post("/scan")
def scan_folder(db: Store = Depends(get_db)):
    """Read the stream folder again (pictures copied in, or taken out, by hand): it isn't read every time the page looks."""
    stream_media.media(db, scan=True)
    return live_stream.page(db)


@router.get("/fonts/{key}")
def get_font(key: str):
    """A font a square's words can be written in, for the page to show them as the stream does. 404 when the server
    doesn't have it (the stream then writes in its own font)."""
    path = live_stream.font_file(key)
    if key not in live_stream.FONTS or path == live_stream.FONT and key != "dejavu-sans":
        raise HTTPException(status_code=404, detail="That font isn't in the Stream plugin.")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="That font isn't in the Stream plugin.")
    kind = "font/otf" if path.endswith(".otf") else "font/ttf"
    return FileResponse(path, media_type=kind, headers={"Cache-Control": "max-age=86400"})


@router.get("/slideshows/{name}/pictures/{picture}")
def get_slideshow_picture(name: str, picture: str, db: Store = Depends(get_db)):
    return _picture_answer(*_media(lambda: stream_media.picture(db, name, picture)))


@router.post("/slideshows/{name}/pictures", status_code=201)
async def add_slideshow_pictures(name: str, files: list[UploadFile] = File(...), db: Store = Depends(get_db)):
    """Pictures into a slideshow's folder (made when it isn't there). While live and it's shown, the stream starts again."""
    for file in files:
        data = await file.read(stream_media.PICTURE_MAX + 1)
        _media(lambda: stream_media.add_picture(db, name, file.filename or "", data))
    _restart_if_used(db, name)
    return live_stream.page(db)


@router.delete("/slideshows/{name}/pictures/{picture}")
def delete_slideshow_picture(name: str, picture: str, confirm: bool = Query(False), db: Store = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: stream_media.remove_picture(db, name, picture))
    _restart_if_used(db, name)
    return live_stream.page(db)


# ------------------------------------------------------------------ the music: MP3s in the stream folder's music/
# Tracks added while live join the music's next round; it isn't stopped for them.


class TryVolumeIn(BaseModel):
    volume: int | None = Field(None, ge=0, le=100)  # None: back to the saved volume


@router.post("/music-volume")
def try_music_volume(payload: TryVolumeIn):
    """The volume slider moved on the page: the music going out follows it straight away, without saving it. The page
    says it again every few seconds while it stays, and sends {volume: null} when it's left (or the change undone); a
    volume not said again for 20 seconds goes back to the saved one by itself. (Not live: nothing to do.)"""
    live_stream.stream.try_volume(payload.volume)
    return {"volume": payload.volume}


@router.post("/music/{action}")
def music_control(action: str, db: Store = Depends(get_db)):
    """The music going out while live: play, pause, next (the next track) or back (the track playing from its start,
    or in its first 3 seconds the one before). 422 when not live, or the music is off."""
    if action not in ("play", "pause", "next", "back"):
        raise HTTPException(status_code=404, detail="Not Found")
    with answer_errors():
        live_stream.stream.music_control(action)
    return live_stream.page(db)


@router.get("/music/{name}")
def get_track(name: str, db: Store = Depends(get_db)):
    """A track, for the page to play it."""
    path = _media(lambda: stream_media.track_path(db, name))
    return FileResponse(path, media_type=stream_media.TRACK_TYPES[path.suffix.lower()], headers={"Cache-Control": "no-cache"})


@router.post("/music", status_code=201)
async def add_tracks(files: list[UploadFile] = File(...), db: Store = Depends(get_db)):
    """MP3s into the music (under 50 MB each; bigger ones can be copied in by hand)."""
    for file in files:
        data = await file.read(stream_media.TRACK_MAX + 1)
        _media(lambda: stream_media.add_track(db, file.filename or "", data))
    return live_stream.page(db)


@router.delete("/music/{name}")
def delete_track(name: str, confirm: bool = Query(False), db: Store = Depends(get_db)):
    require_confirm(confirm)
    _media(lambda: stream_media.remove_track(db, name))
    return live_stream.page(db)



# ------------------------------------------------------------------ Farmhand's Stream control
# Farmhand starts and stops the stream from its Stream control page (the manifest's stream_control path). Each answers
# {live, following (Stream control's design is sent, not the plugin's own layout), error, watch_url}.

control = APIRouter(prefix="/api/stream-control", tags=["stream-control"])


def _control_status(db: Store) -> dict:
    status, channel = live_stream.stream.status(), live_stream.settings(db)["channel"]
    return {"live": status["live"], "following": stream_control.follower.following(),
            "error": status["error"] or stream_control.follower.error(),
            "watch_url": f"https://www.twitch.tv/{channel}" if channel else None}


@control.get("")
def control_status(db: Store = Depends(get_db)):
    return _control_status(db)


@control.post("/start")
def control_start(db: Store = Depends(get_db)):
    """Go live, with Stream control's design when it's followed (asked of Farmhand now, so it's the latest). 422 says
    why not, in plain words (no stream key yet, say)."""
    stream_control.follower.check()
    with answer_errors():
        live_stream.stream.go_live(db, session_factory)
    return _control_status(db)


@control.post("/stop")
def control_stop(db: Store = Depends(get_db)):
    live_stream.stream.stop()
    return _control_status(db)
