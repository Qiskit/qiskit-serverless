"""Unit tests for SchedulerHttpServer."""

import json
import urllib.error
import urllib.request

from django.test import TestCase

from scheduler.http_server import SchedulerHttpServer
from scheduler.views.probes import liveness, readiness

SCHEDULER_PORT = 8000
SITE_HOST = f"http://127.0.0.1:{SCHEDULER_PORT}"


class TestSchedulerHttpServer(TestCase):
    """Tests for SchedulerHttpServer."""

    def setUp(self):
        self.http_server = SchedulerHttpServer(site_host=SITE_HOST)
        self.http_server.add_path_handler("/readiness", readiness)
        self.http_server.add_path_handler("/liveness", liveness)

    def tearDown(self):
        self.http_server.stop()

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
