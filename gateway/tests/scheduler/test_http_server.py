"""Unit tests for SchedulerHttpServer."""

import json
import urllib.error
import urllib.request

from django.test import TestCase

from scheduler.http_server import SchedulerHttpServer
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

# Scheduler and Gateway share the same settings and the same SITE_HOST value. We need to override it
# during tests to avoid collisions

SITE_HOST = "http://127.0.0.1:8100"


class TestSchedulerHttpServer(TestCase):
    """Tests for SchedulerHttpServer."""

    def setUp(self):
        self.http_server = SchedulerHttpServer(site_host=SITE_HOST)
        self.http_server.configure_routes(SchedulerMetrics())

    def tearDown(self):
        self.http_server.stop()

    def test_start_tops(self):
        """HTTP server start stop flow"""

        self.http_server.start()
        assert self.http_server._thread is not None
        assert self.http_server._httpd is not None
        assert self.http_server.is_running() == True

        self.http_server.stop()
        assert self.http_server._thread is None
        assert self.http_server._httpd is None
        assert self.http_server.is_running() == False

    def test_readiness(self):
        """HTTP server responds to /readiness"""
        self.http_server.start()

        url = f"{SITE_HOST}/readiness"
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            data = json.loads(response.read().decode())
            assert data["status"] == "ready"

    def test_liveness(self):
        """HTTP server responds to /liveness"""
        self.http_server.start()

        url = f"{SITE_HOST}/liveness"
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "application/json"
            data = json.loads(response.read().decode())
            assert data["status"] == "alive"

    def test_notfound(self):
        """HTTP server responds with 404 for unknown paths"""
        self.http_server.start()

        url = f"{SITE_HOST}/this_path_does_not_exist"
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(url)

        error = context.exception
        assert error.code == 404
        body = error.read().decode()
        assert body == "Not found"

    def test_metrics(self):
        """test the /metrics endpoint works"""
        self.http_server.start()

        url = f"{SITE_HOST}/metrics"
        with urllib.request.urlopen(url) as response:
            assert response.status == 200
            assert "text/plain" in response.headers["Content-Type"]
