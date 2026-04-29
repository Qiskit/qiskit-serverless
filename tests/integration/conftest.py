# pylint: disable=import-error, invalid-name
"""Fixtures for tests.

This module provides pytest fixtures for integration tests.
It assumes the server is pre-started externally (via docker-compose or kubernetes).
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2
from pytest import fixture
from qiskit_serverless import ServerlessClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")

# Port must match RUNTIME_INSTANCES_API_BASE_URL configured in the gateway Docker container.
# Default matches docker-compose: http://host.docker.internal:8111
INSTANCES_SERVER_LOCAL_PORT = int(os.environ.get("INSTANCES_SERVER_LOCAL_PORT", "8111"))

DATABASE_HOST = os.environ.get("DATABASE_HOST", "localhost")
DATABASE_PORT = int(os.environ.get("DATABASE_PORT", "5432"))
DATABASE_NAME = os.environ.get("DATABASE_NAME", "serverlessdb")
DATABASE_USER = os.environ.get("DATABASE_USER", "serverlessuser")
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "serverlesspassword")


@fixture(scope="session", autouse=True)
def _enable_instances_api():
    """Enable the Runtime instances API feature flag in the gateway DB."""
    conn = psycopg2.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        dbname=DATABASE_NAME,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_config (name, value, description, created, updated)
                    VALUES (%s, 'true', '', NOW(), NOW())
                    ON CONFLICT (name) DO UPDATE SET value = 'true'
                    """,
                    ["gateway.runtime_instances_api.enabled"],
                )
    finally:
        conn.close()


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=GATEWAY_INSTANCE,
        channel=GATEWAY_CHANNEL,
    )


class InstancesHandler(BaseHTTPRequestHandler):
    """HTTP handler that returns the configured response for any GET request."""

    def do_GET(self):
        """Serve the configured response."""
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
        """Suppress default request logging."""


class InstancesServer:
    """Wrapper around HTTPServer with a clean API for configuring instances API responses.

    Usage:
        instances_server.grant("my-provider", "my-function", ["function.provider.jobs"])
        instances_server.reset()    # clears all grants (empty list, has_response=True)
        instances_server.error(500) # gateway falls back to Django groups
    """

    def __init__(self, httpd: HTTPServer):
        self._httpd = httpd
        self.reset()

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
        """Clear all grants (returns has_response=True with empty function list)."""
        self._httpd.response_config = {"status": 200, "body": {"functions": []}}
        return self

    def error(self, status: int = 500) -> "InstancesServer":
        """Respond with an error status (gateway falls back to Django groups)."""
        self._httpd.response_config = {"status": status}
        return self


@fixture(scope="session", autouse=True)
def instances_server():
    """Start a real HTTP server that simulates the external instances API.

    Autouse: always running for all integration tests, so any new endpoint that uses
    the instances client path will fail if it doesn't call instances_server.grant() first.

    Binds to 0.0.0.0 so the gateway Docker container can reach it via host.docker.internal.
    """
    httpd = HTTPServer(("0.0.0.0", INSTANCES_SERVER_LOCAL_PORT), InstancesHandler)
    t = threading.Thread(target=httpd.serve_forever)
    t.daemon = True
    t.start()
    server = InstancesServer(httpd)
    yield server
    httpd.shutdown()
    t.join()


@fixture(autouse=True)
def _reset_instances_server(instances_server):  # pylint: disable=redefined-outer-name
    """Reset the instances server to empty grants before each test."""
    instances_server.reset()
