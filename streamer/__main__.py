"""Start the plugin: python -m streamer (what the Dockerfile runs)."""
from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn

from . import camera_watch, config, save_location, store, stream_control
from .app import app
from .live_stream import stream


@asynccontextmanager
async def _running(_app):
    """While the plugin runs (set here, not in app.py, so tests using the app never go live by themselves)."""
    s = store.store()
    save_location.ensure(s)  # the save location on the NAS mounted again (a mount is gone once the container restarts)
    camera_watch.start()  # the cameras kept in step with Farmhand (the Clip drop-down follows cameras added or removed)
    try:  # Stream control asked first, so a stream live before the restart comes back with the layout it's to send
        stream_control.follower.check()
    except Exception as e:  # noqa: BLE001 - asked again every few seconds
        print(f"stream: asking Stream control failed ({e})", flush=True)
    stream_control.follower.start()
    stream.resume(s, store.session_factory)  # live before the restart: live again
    yield
    # (only the container stopping: it goes live again when it starts)
    stream_control.follower.stop()
    camera_watch.stop()
    stream.stop(forget=False)


app.router.lifespan_context = _running


def main() -> None:
    settings = config.settings
    print(f"stream: listening on port {settings.port}; Farmhand is at {settings.farmhand_url or '(FARMHAND_URL not set)'}; "
          f"stream folder {settings.media_dir}; settings in {settings.data_dir}"
          + (f"; TRYING OUT: the stream goes to {settings.test_destination}, never to Twitch" if settings.test_destination else ""),
          flush=True)
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
