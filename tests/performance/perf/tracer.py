"""Records every HTTP call the client makes, by wrapping requests.Session.send."""

import json
import queue
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

_ID = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)")
_CONTEXT = threading.local()


def set_context(**fields) -> None:
    """Tag the calls of this thread, for example with the user."""
    _CONTEXT.fields = fields


def normalize_path(url: str) -> str:
    """The URL path with every id replaced by {id}. A call to another host keeps only its host and last segment."""
    parts = urlsplit(url)
    if "/api/" in parts.path:
        return _ID.sub("/{id}", parts.path)
    return f"{parts.hostname}/.../{parts.path.rsplit('/', 1)[-1]}"


class Tracer:
    """Writes one line per call to calls.jsonl, from a single writer thread."""

    def __init__(self, path: Path):
        self._path = path
        self._queue: queue.Queue = queue.Queue()
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._original_send = requests.Session.send

    def start(self) -> None:
        """Start recording."""
        self._writer.start()
        tracer = self

        def send(session, request, **kwargs):
            return tracer.send(session, request, **kwargs)

        requests.Session.send = send

    def send(self, session, request, **kwargs):
        """Send the request with the original Session.send, and record it."""
        started = time.monotonic()
        row = {
            "start": time.time(),
            "method": request.method,
            "path": normalize_path(request.url),
            **getattr(_CONTEXT, "fields", {}),
        }
        try:
            response = self._original_send(session, request, **kwargs)
        except Exception as exc:
            row.update(seconds=time.monotonic() - started, status=None, error=type(exc).__name__)
            self._queue.put(row)
            raise
        # a redirect, for example /logs/ to COS, is followed inside this call and recorded as its own row
        first = (response.history or [response])[0]
        server_ms = first.headers.get("x-envoy-upstream-service-time")
        row.update(
            seconds=first.elapsed.total_seconds() if response.history else time.monotonic() - started,
            status=first.status_code,
            server_seconds=int(server_ms) / 1000 if server_ms and server_ms.isdigit() else None,
            html=first.status_code >= 400 and first.headers.get("content-type", "").startswith("text/html"),
        )
        self._queue.put(row)
        return response

    def stop(self) -> None:
        """Stop recording and flush the file."""
        requests.Session.send = self._original_send
        self._queue.put(None)
        self._writer.join()

    def _write(self) -> None:
        with self._path.open("a") as file:
            while (row := self._queue.get()) is not None:
                file.write(json.dumps(row) + "\n")
                file.flush()
