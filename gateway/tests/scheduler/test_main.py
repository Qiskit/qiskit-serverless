"""Unit tests for scheduler main loop."""

import pytest
from unittest.mock import MagicMock

from scheduler.main import Main

# Scheduler and Gateway share the same settings and the same SITE_HOST value. We need to override it
# during tests to avoid collisions

SITE_HOST = "http://127.0.0.1:8200"


class TestMain:
    """Tests for scheduler Main service."""

    @pytest.fixture(autouse=True)
    def _setup(self, settings, db):
        settings.SITE_HOST = SITE_HOST
        self.scheduler_main = Main()
        yield
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

    def test_task_fails(self):
        """When a task raises, metrics.increase_task_failure should be called."""
        failing_task = MagicMock()
        failing_task.name = "failing_task"
        failing_task.run.side_effect = Exception("boom")

        def stop_loop():
            self.scheduler_main.kill_signal.received = True

        stop_task = MagicMock()
        stop_task.run.side_effect = stop_loop

        self.scheduler_main.tasks = [failing_task, stop_task]
        self.scheduler_main.metrics = MagicMock()

        self.scheduler_main.run()
        self.scheduler_main.metrics.increase_task_failure.assert_called_once_with("failing_task")

    def test_http_server_starts_and_stops(self):
        """HTTP server should start and stop after loop ends."""
        self.scheduler_main.start_http_server()
        # kill_signal to True makes the loop exits immediately
        self.scheduler_main.kill_signal.received = True
        self.scheduler_main.tasks = []
        self.scheduler_main.run()
        assert self.scheduler_main.http_server.is_running() == False

    def test_loop_iteration_records_metrics(self):
        """Each loop iteration should call observe_scheduler_iteration."""

        def stop_loop():
            self.scheduler_main.kill_signal.received = True

        task = MagicMock()
        task.run.side_effect = stop_loop

        self.scheduler_main.tasks = [task]
        self.scheduler_main.metrics = MagicMock()

        self.scheduler_main.run()

        self.scheduler_main.metrics.observe_scheduler_iteration.assert_called_once()
        args = self.scheduler_main.metrics.observe_scheduler_iteration.call_args[0]
        elapsed, timestamp = args
        assert elapsed >= 0
        assert timestamp > 0
