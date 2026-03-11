"""Scheduler HTTP server primitives."""

import logging
import socket
import threading
import time
from http import HTTPStatus
from urllib.parse import urlparse
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse

from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.views.probes import liveness, not_found, readiness

logger = logging.getLogger("main")


class SchedulerHttpServer:
    """Expose scheduler probes and Prometheus metrics via WSGI."""

    def __init__(self, site_host: str):
        parsed = urlparse(site_host)
        self._site_host = site_host
        self._host = parsed.hostname
        self._port = parsed.port
        self._routes: dict = {}
        self._not_found_handler = create_request_handler(not_found)
        self._httpd: WSGIServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def configure_routes(self, scheduler_metrics: SchedulerMetrics) -> None:
        """Configure standard routes (probes and optionally metrics)."""
        self.add_path_handler("/readiness", readiness)
        self.add_path_handler("/liveness", liveness)
        self.add_wsgi_handler("/metrics", scheduler_metrics.wsgi_app)

    def add_path_handler(self, path: str, func):
        """Register a handler for the given path."""
        self.add_wsgi_handler(path, create_request_handler(func))

    def add_wsgi_handler(self, path: str, wsgi_handler):
        """Register a raw WSGI application for the given path (no Django wrapper)."""
        logger.info("Adding %s", path)
        self._routes[path] = wsgi_handler

    def set_not_found_handler(self, func):
        """Set the handler for unmatched paths."""
        self._not_found_handler = create_request_handler(func)

    def _app(self, environ, start_response):
        path = environ.get("PATH_INFO", "").rstrip("/") or "/"
        handler = self._routes.get(path, self._not_found_handler)
        return handler(environ, start_response)

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        if self._running:
            raise RuntimeError("Scheduler HTTP server already running!")
        if not self._not_found_handler:
            raise RuntimeError("Not found handler not configured. Call add_not_found_handler first.")

        self._httpd = make_server(self._host, self._port, self._app, handler_class=_QuietHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        if not self._wait_for_server():
            self.stop()
            raise RuntimeError(f"HTTP server failed to start on {self._site_host}")
        self._running = True
        logger.info("Scheduler HTTP server started on %s", self._site_host)

    def _wait_for_server(self, timeout: float = 1.0) -> bool:
        """Wait until the server is accepting connections."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                with socket.create_connection((self._host, self._port), timeout=0.1):
                    return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.01)
        return False

    def is_running(self) -> bool:
        """Return True if the server is currently running."""
        return self._running

    def stop(self) -> None:
        """Stop the HTTP server and clean up resources."""
        if not self._running:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        self._httpd = None
        self._running = False
        logger.info("Scheduler HTTP server stopped")


class _QuietHandler(WSGIRequestHandler):
    """WSGI handler that only logs errors (5xx status codes)."""

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        pass

    def log_error(self, format, *args):  # pylint: disable=redefined-builtin
        logger.error("HTTP %s", format % args if args else format)


def create_request_handler(func):
    """Create a handler for a WSGI server to process a http request."""

    def handler(environ, start_response):
        request = WSGIRequest(environ)
        response = func(request)
        if not isinstance(response, HttpResponse):
            raise TypeError(f"Handler must return HttpResponse, got {type(response).__name__}")
        start_response(
            f"{response.status_code} {HTTPStatus(response.status_code).phrase}",
            list(response.items()),
        )
        return [response.content]

    return handler
