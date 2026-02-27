"""Scheduler HTTP server primitives."""

import logging
import threading
from http import HTTPStatus
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.core.handlers.wsgi import WSGIRequest

logger = logging.getLogger("main")


class _SilentHandler(WSGIRequestHandler):
    """WSGI handler that does not log requests."""

    def log_message(self, *args):
        pass


class SchedulerHttpServer:
    """Expose scheduler probes and Prometheus metrics via WSGI."""

    def __init__(self, port: int, host: str = "0.0.0.0"):
        self._host = host
        self._port = port
        self._routes: dict = {}
        self._httpd: WSGIServer | None = None
        self._thread: threading.Thread | None = None

    def add_handler(self, path: str, handler):
        self._routes[path] = handler

    def add_json_handler(self, path: str, func):
        def handler(environ, start_response):
            response = func(WSGIRequest(environ))
            start_response(
                f"{response.status_code} {HTTPStatus(response.status_code).phrase}",
                list(response.items()),
            )
            return [response.content]

        self._routes[path] = handler

    def _app(self, environ, start_response):
        path = environ.get("PATH_INFO", "").rstrip("/") or "/"
        handler = self._routes.get(path)
        if handler:
            return handler(environ, start_response)
        start_response("404 Not Found", [("Content-Type", "application/json")])
        return [b'{"status":"not_found"}']

    def start(self) -> None:
        if self._httpd:
            return
        self._httpd = make_server(self._host, self._port, self._app, handler_class=_SilentHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Scheduler HTTP server started on port %d", self._port)

    def stop(self) -> None:
        if not self._httpd:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._httpd = self._thread = None
        logger.info("Scheduler HTTP server stopped.")
