"""Unit tests for scheduler main loop."""

from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from scheduler.main import Main

# Scheduler and Gateway share the same settings and the same SITE_HOST value. In production, both services start
# with different environment variables. In testing, SITE_HOST is defined once in the 8000 port. So we need to override
#

SCHEDULER_PORT = 8000
SITE_HOST = f"http://127.0.0.1:{SCHEDULER_PORT}"


@override_settings(SITE_HOST=SITE_HOST)
class TestMain(TestCase):
    """Tests for scheduler Main service."""

    def setUp(self):
        self.scheduler_main = Main()

    def tearDown(self):
        self.scheduler_main.stop_http_server()

    def test_run_executes_tasks(self):
        """run should execute tasks and stop when kill signal is received."""
        called = False

        def run_side_effect():
            nonlocal called
            called = True
            self.scheduler_main.kill_signal.received = True

        task = MagicMock()
        task.run.side_effect = run_side_effect

        self.scheduler_main.tasks = [task]
        self.scheduler_main.run()

        assert called == True
        assert task.run.call_count == 1

    def test_http_server_starts_and_stops(self):
        """HTTP server should start and stop after loop ends."""
        self.scheduler_main.start_http_server()
        # kill_signal to True makes the loop exits immediately
        self.scheduler_main.kill_signal.received = True
        self.scheduler_main.tasks = []
        self.scheduler_main.run()
        assert self.scheduler_main.http_server._httpd is None
