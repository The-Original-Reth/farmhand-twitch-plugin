"""
A stand-in for Farmhand's plugin API (/plugin-api/v1), answering in exactly its shapes (docs/plugins.md): the token
checked, permissions checked, 429 on demand, the farm's cameras and each printer's print, and the copy of the plugin's
settings it keeps (stream:backup: PUT and GET /backup). Copied from the Hello
plugin's tests, with what the stream plugins read added. `down` makes it answer
nothing at all, as a stopped Farmhand.
"""
from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "good-token"
EVERYTHING = {"printers:read", "prints:read", "farm:read", "cameras:read", "stream:backup", "stream:read"}
MJPEG = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "5",
         "-rw_timeout", "10000000", "-use_wallclock_as_timestamps", "1", "-f", "mpjpeg"]


def camera(name: str, url: str, error: str | None = None, rotation: int = 0) -> dict:
    """A camera as Farmhand's /cameras gives it."""
    return {"name": name, "kind": None if error else "mjpeg", "url": None if error else url,
            "ffmpeg_input": None if error else [*MJPEG, "-i", url], "rotation": rotation, "flip_horizontal": False,
            "flip_vertical": False, "ffmpeg_filters": ["transpose=1"] if rotation == 90 else [], "aspect_ratio": "4:3",
            "target_fps": 15, "snapshot_url": None, "error": error}


class FakeFarmhand:
    def __init__(self, port: int = 0):
        self.printers = [
            {"id": 1, "name": "VT 1190", "kind": "Voron Trident", "connection_type": "moonraker", "addresses": {}},
            {"id": 2, "name": "Core One", "kind": None, "connection_type": "prusalink", "addresses": {}},
        ]
        self.prints = {
            1: {"state": "printing", "progress": 42.4, "file": "Frog.gcode", "error": None},
            2: {"state": None, "progress": None, "file": None, "error": None},
        }
        self.cameras = {
            1: {"printer_id": 1, "printer_name": "VT 1190", "error": None,
                "cameras": [camera("Bed", "http://10.0.6.21/webcam/?action=stream")]},
            2: {"printer_id": 2, "printer_name": "Core One", "error": None,
                "cameras": [camera("Camera", "http://10.0.6.30/stream"), camera("Nozzle", "", error="Core One's Nozzle camera only plays in a browser (WebRTC).")]},
        }
        # Stream control: its design while this plugin is ticked in it (None: {"enabled": false}), the media it lists,
        # and the files Farmhand hands over, by their path under /stream ("pictures/logo.png", "music/beat.mp3"...)
        self.design: dict | None = None
        self.media = {"images": [], "slideshows": [], "music": [], "error": None}
        self.files: dict[str, bytes] = {}
        self.files_busy_for = 0  # the next this-many file downloads get 429 (Retry-After: 1)
        # stream:backup: the copy of the plugin's settings kept ({format, saved_at, settings}; None: none yet), and every
        # backup PUT, as sent
        self.backup: dict | None = None
        self.backups_put: list[dict] = []
        self.down = False  # True: nothing answers (Farmhand stopped)
        self.permissions = set(EVERYTHING)
        self.busy_for = 0  # the next this-many calls get 429
        self.calls: list[str] = []
        self._listeners: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._sequence = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                fake.calls.append(self.path)
                if fake.down:
                    return self.close_connection_now()
                fake.answer(self)

            def do_POST(self):
                fake.calls.append("POST " + self.path)
                if fake.down:
                    return self.close_connection_now()
                fake.answer(self, post=True)

            def do_PUT(self):
                fake.calls.append("PUT " + self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if fake.down:
                    return self.close_connection_now()
                fake.answer(self, put=body)

            def close_connection_now(self):
                self.close_connection = True
                try:
                    self.connection.shutdown(2)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/plugin-api/v1"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def stop(self):
        with self._lock:
            for q in self._listeners:
                q.put(None)  # ends each event stream
        self.server.shutdown()
        self.server.server_close()

    # ------------------------------------------------------------------ what the test does

    def push(self, kind: str, **data):
        """An event, to everyone listening on /events."""
        with self._lock:
            self._sequence += 1
            event = {"id": self._sequence, "type": kind, "at": "2026-11-11T14:02:11+00:00", **data}
            for q in self._listeners:
                q.put(event)

    def listening(self) -> int:
        with self._lock:
            return len(self._listeners)

    # ------------------------------------------------------------------ the plugin API

    def answer(self, h: BaseHTTPRequestHandler, post: bool = False, put: bytes | None = None):
        if h.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self.send(h, 401, {"detail": "That plugin token isn't valid: it was replaced by a new one."})
        if self.busy_for > 0:
            self.busy_for -= 1
            return self.send(h, 429, {"detail": "This plugin is asking Farmhand too often."}, {"Retry-After": "1"})
        path = h.path.removeprefix("/plugin-api/v1")
        if path == "/me":
            return self.send(h, 200, {"plugin_id": "twitch", "permissions": sorted(self.permissions), "api_version": "1"})
        if path == "/cameras":
            return self.allowed(h, "cameras:read") and self.send(h, 200, {"printers": list(self.cameras.values())})
        if path == "/printers":
            return self.allowed(h, "printers:read") and self.send(h, 200, {"printers": self.printers})
        if path.startswith("/printers/") and path.endswith("/print"):
            pid = int(path.split("/")[2])
            if pid not in self.prints:
                return self.send(h, 404, {"detail": "Printer not found"})
            return self.allowed(h, "prints:read") and self.send(h, 200, self.prints[pid])
        if path == "/farm":
            return self.allowed(h, "farm:read") and self.send(h, 200, {
                "scheme": "farmhand", "mode": "dark", "time_zone": "Europe/London",
                "colors": {"bg": "#1B1D1E", "amber": "#E39F3A"},
            })
        if path == "/backup":
            return self.allowed(h, "stream:backup") and self.answer_backup(h, put)
        if path == "/stream/design":
            if not self.allowed(h, "stream:read"):
                return
            if self.design is None:
                return self.send(h, 200, {"enabled": False})
            return self.send(h, 200, {"enabled": True, "design": self.design, "media": self.media})
        if path.startswith("/stream/"):
            from urllib.parse import unquote

            name = unquote(path.removeprefix("/stream/"))
            if not self.allowed(h, "stream:read"):
                return
            if self.files_busy_for > 0:
                self.files_busy_for -= 1
                return self.send(h, 429, {"detail": "This plugin is asking Farmhand too often."}, {"Retry-After": "1"})
            if self.design is None or name not in self.files:
                return self.send(h, 404, {"detail": "That file isn't there."})
            return self.send_bytes(h, self.files[name])
        if path == "/events":
            return self.allowed(h, "prints:read") and self.events(h)
        self.send(h, 404, {"detail": "Not Found"})

    def answer_backup(self, h, put: bytes | None) -> bool:
        """GET /backup: the copy kept, or 404 while there's none. PUT /backup: {format: 1, saved_at, settings: {str: str}}
        (at most 2 MiB) kept, answered {saved_at}."""
        if put is None:
            if self.backup is None:
                return self.send(h, 404, {"detail": "Farmhand has no copy of this plugin's settings."})
            return self.send(h, 200, self.backup)
        if len(put) > 2 * 1024 * 1024:
            return self.send(h, 413, {"detail": "That backup is bigger than 2 MiB."})
        body = json.loads(put)
        settings = body.get("settings")
        if body.get("format") != 1 or not isinstance(settings, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in settings.items()):
            return self.send(h, 422, {"detail": "That isn't a backup Farmhand can keep."})
        self.backups_put.append(body)
        self.backup = {"format": 1, "saved_at": body["saved_at"], "settings": settings}
        return self.send(h, 200, {"saved_at": body["saved_at"]})

    def allowed(self, h, permission: str) -> bool:
        if permission in self.permissions:
            return True
        self.send(h, 403, {"detail": f"The \"stream\" plugin hasn't been given the {permission} permission, which this needs."})
        return False

    def send(self, h, status: int, body: dict, headers: dict | None = None) -> bool:
        data = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(data)
        return True

    def send_bytes(self, h, data: bytes) -> bool:
        h.send_response(200)
        h.send_header("Content-Type", "application/octet-stream")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return True

    def events(self, h):
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._listeners.append(q)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Connection", "close")
        h.end_headers()
        h.close_connection = True
        try:
            h.wfile.write(b": connected\n\n")
            h.wfile.flush()
            while True:
                event = q.get()
                if event is None:
                    return
                h.wfile.write(f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n".encode())
                h.wfile.flush()
        except OSError:
            pass
        finally:
            with self._lock:
                self._listeners.remove(q)
