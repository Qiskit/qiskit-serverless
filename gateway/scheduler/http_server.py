"""Scheduler HTTP server primitives."""

import logging
import threading
from http import HTTPStatus
from urllib.parse import urlparse
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse

from scheduler.views.probes import not_found

logger = logging.getLogger("main")


class _SilentHandler(WSGIRequestHandler):
    """WSGI handler that does not log requests."""

    def log_message(self, *args):
        pass


class SchedulerHttpServer:
    """Expose scheduler probes and Prometheus metrics via WSGI."""

    def __init__(self, site_host: str):
        self._site_host = site_host
        self._routes: dict = {}
        self._not_found_handler = self._create_handler(not_found)
        self._httpd: WSGIServer | None = None
        self._thread: threading.Thread | None = None

    def add_path_handler(self, path: str, func):
        logger.info(f"Adding {path}")
        self._routes[path] = self._create_handler(func)

    def add_not_found_handler(self, func):
        self._not_found_handler = self._create_handler(func)

    def _create_handler(self, func):
        def handler(environ, start_response):
            response = func(WSGIRequest(environ))
            if not isinstance(response, HttpResponse):
                raise TypeError(f"Handler must return HttpResponse, got {type(response).__name__}")
            start_response(
                f"{response.status_code} {HTTPStatus(response.status_code).phrase}",
                list(response.items()),
            )
            return [response.content]

        return handler

    def _app(self, environ, start_response):
        path = environ.get("PATH_INFO", "").rstrip("/") or "/"
        handler = self._routes.get(path, self._not_found_handler)
        return handler(environ, start_response)

    def start(self) -> None:
        if self._httpd:
            raise RuntimeError("Scheduler HTTP server already running!")
        if not self._not_found_handler:
            raise RuntimeError("Not found handler not configured. Call add_not_found_handler first.")

        parsed = urlparse(self._site_host)
        host = parsed.hostname or "0.0.0.0"
        port = parsed.port or 8001

        self._httpd = make_server(host, port, self._app, handler_class=_SilentHandler)
        ready_event = threading.Event()

        def func():
            ready_event.set()
            self._httpd.serve_forever()

        self._thread = threading.Thread(target=func, daemon=True)
        self._thread.start()
        ready_event.wait()
        logger.info("Scheduler HTTP server started on %s", self._site_host)

    def stop(self) -> None:
        if not self._httpd:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._httpd = self._thread = None
        logger.info("Scheduler HTTP server stopped.")
