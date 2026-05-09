"""Fixtures for FunctionAccessClient tests."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.request_count += 1
        cfg = self.server.response_config
        body = json.dumps(cfg["body"]).encode() if "body" in cfg else b""
        self.send_response(cfg["status"])
        if body:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):
        pass


class InstancesServer:
    """Wrapper around HTTPServer with a clean API for configuring instances API responses.

    Usage:
        instances_server.grant("my-provider", "my-function", ["function.run"])
        instances_server.reset()   # clears all grants (empty list, use_legacy_authorization=False)
    """

    def __init__(self, httpd: HTTPServer):
        self._httpd = httpd
        self.reset()

    @property
    def request_count(self) -> int:
        """Number of HTTP requests received by the server."""
        return self._httpd.request_count

    def grant(
        self,
        provider: str,
        function: str,
        permissions: list,
        business_model: str = "subsidized",
    ) -> "InstancesServer":
        """Grant permissions to a function. Replaces any existing entry for provider+function."""
        body = self._httpd.response_config.get("body") or {}
        functions = [f for f in body.get("functions", []) if not (f["provider"] == provider and f["name"] == function)]
        functions.append(
            {
                "provider": provider,
                "name": function,
                "business_model": business_model,
                "permissions": list(permissions),
            }
        )
        self._httpd.response_config = {"status": 200, "body": {"functions": functions}}
        return self

    def reset(self) -> "InstancesServer":
        """Clear all grants (returns use_legacy_authorization=False with empty function list)."""
        self._httpd.response_config = {"status": 200, "body": {"functions": []}}
        return self

    def error(self, status: int = 500) -> "InstancesServer":
        """Respond with an error status (gateway falls back to Django groups)."""
        self._httpd.response_config = {"status": status}
        return self


@pytest.fixture
def instances_server(settings):
    """Real HTTP server on a random port simulating the external instances API."""
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.request_count = 0
    t = threading.Thread(target=httpd.serve_forever)
    t.daemon = True
    t.start()
    server = InstancesServer(httpd)
    settings.RUNTIME_API_BASE_URL = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield server
    httpd.shutdown()
    t.join()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear Django cache before and after each test to avoid cross-test pollution."""
    from django.core.cache import cache  # pylint: disable=import-outside-toplevel

    cache.clear()
    yield
    cache.clear()
