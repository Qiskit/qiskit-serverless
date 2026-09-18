"""Fixtures for FunctionAccessClient tests."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.request_count += 1
        cfg = self.server.response_config
        body = self._body(cfg)
        self.send_response(cfg["status"])
        if body:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self, cfg) -> bytes:
        """Serialize the configured response.

        An ``element`` is wrapped in the endpoint's envelope here rather than in ``InstancesServer``,
        because only the handler sees the request and the element has to carry the CRN that was
        asked for: the client selects its element by that field. A ``body`` is sent verbatim, which
        is how a test produces an envelope describing some other instance.
        """
        if "element" in cfg:
            element = {"instance_crn": self.headers.get("Service-CRN"), **cfg["element"]}
            return json.dumps({"instance_entitlements": [element]}).encode()
        if "body" in cfg:
            return json.dumps(cfg["body"]).encode()
        return b""

    def log_message(self, *args):
        pass


class InstancesServer:
    """Wrapper around HTTPServer with a clean API for configuring instances API responses.

    Usage:
        instances_server.grant("my-provider", "my-function", ["function.run"])
        instances_server.reset()   # grants nothing (use_legacy_authorization=False)
    """

    def __init__(self, httpd: HTTPServer):
        self._httpd = httpd
        self.reset()

    @property
    def request_count(self) -> int:
        """Number of HTTP requests received by the server."""
        return self._httpd.request_count

    def _element(self) -> dict:
        return dict(self._httpd.response_config.get("element") or {})

    def _set_element(self, element: dict) -> "InstancesServer":
        self._httpd.response_config = {"status": 200, "element": element}
        return self

    def grant(
        self,
        provider: str,
        function: str,
        permissions: list,
        business_model: str = "subsidized",
    ) -> "InstancesServer":
        """Grant permissions to a function. Replaces any existing entry for provider+function."""
        element = self._element()
        functions = [
            f for f in element.get("functions", []) if not (f["provider"] == provider and f["name"] == function)
        ]
        functions.append(
            {
                "provider": provider,
                "name": function,
                "business_model": business_model,
                "permissions": list(permissions),
            }
        )
        element["functions"] = functions
        return self._set_element(element)

    def grant_custom(self, permissions: list) -> "InstancesServer":
        """Set custom_functions permissions in the response element."""
        element = self._element()
        element["custom_functions"] = {"permissions": list(permissions)}
        return self._set_element(element)

    def clear_custom(self) -> "InstancesServer":
        """Set custom_functions to null, which the client must coalesce rather than dereference."""
        element = self._element()
        element["custom_functions"] = None
        return self._set_element(element)

    def instance_error(self, code: int, message: str = "instance error") -> "InstancesServer":
        """Answer with a per-instance error element instead of entitlements (1279, 1289)."""
        return self._set_element({"error": {"code": code, "message": message}})

    def other_instance(self, instance_crn: str) -> "InstancesServer":
        """Answer with an envelope whose only element describes a different instance."""
        self._httpd.response_config = {
            "status": 200,
            "body": {"instance_entitlements": [{"instance_crn": instance_crn}]},
        }
        return self

    def reset(self) -> "InstancesServer":
        """Grant nothing. The endpoint omits functions and custom_functions when they are empty, so
        an instance entitled to nothing is an element carrying only its CRN."""
        return self._set_element({})

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
