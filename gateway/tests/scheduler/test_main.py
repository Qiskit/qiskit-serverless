"""Unit tests for scheduler main loop."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

from scheduler.main import Main


class TestMain(TestCase):
    """Tests for scheduler Main service."""

    @patch("scheduler.main.logger")
    @patch("scheduler.main.Config.add_defaults")
    def test_configure_registers_signal_and_defaults(self, add_defaults, logger):
        """configure should register kill signal and load config defaults."""
        scheduler_main = Main()
        scheduler_main.kill_signal = MagicMock()

        scheduler_main.configure()

        scheduler_main.kill_signal.register.assert_called_once_with()
        add_defaults.assert_called_once_with()
        logger.info.assert_called_once_with("Scheduler loop started.")

    @patch("scheduler.main.time.sleep")
    @patch("scheduler.main.time.time")
    @patch("scheduler.main.ScheduleQueuedJobs")
    @patch("scheduler.main.FreeResources")
    @patch("scheduler.main.UpdateJobsStatuses")
    def test_run_executes_tasks_and_sleeps_until_next_tick(
        self,
        update_jobs_statuses_cls,
        free_resources_cls,
        schedule_queued_jobs_cls,
        time_mock,
        sleep_mock,
    ):
        """run should execute tasks and sleep to complete one-second cycles."""
        scheduler_main = Main()
        scheduler_main.kill_signal.received = False

        update_task = MagicMock(name="UpdateJobsStatuses")
        free_task = MagicMock(name="FreeResources")
        schedule_task = MagicMock(name="ScheduleQueuedJobs")

        task_calls = {"count": 0}

        def update_task_side_effect():
            task_calls["count"] += 1
            if task_calls["count"] == 2:
                scheduler_main.kill_signal.received = True

        update_task.task.side_effect = update_task_side_effect
        update_jobs_statuses_cls.return_value = update_task
        free_resources_cls.return_value = free_task
        schedule_queued_jobs_cls.return_value = schedule_task
        values = iter([0.0, 0.2, 1.0, 1.0])
        time_mock.side_effect = lambda: next(values, 1.0)

        scheduler_main.run()

        update_jobs_statuses_cls.assert_called_once_with(scheduler_main.kill_signal)
        free_resources_cls.assert_called_once_with(scheduler_main.kill_signal)
        schedule_queued_jobs_cls.assert_called_once_with(scheduler_main.kill_signal)
        self.assertEqual(update_task.task.call_count, 2)
        self.assertEqual(free_task.task.call_count, 1)
        self.assertEqual(schedule_task.task.call_count, 1)
        sleep_mock.assert_called_once_with(0.8)

    @patch("scheduler.main.time.sleep")
    @patch("scheduler.main.time.time", side_effect=[3.0, 3.0])
    @patch("scheduler.main.logger")
    @patch("scheduler.main.ScheduleQueuedJobs")
    @patch("scheduler.main.FreeResources")
    @patch("scheduler.main.UpdateJobsStatuses")
    def test_run_logs_task_exceptions_and_stops_cleanly(
        self,
        update_jobs_statuses_cls,
        free_resources_cls,
        schedule_queued_jobs_cls,
        logger,
        _time_mock,
        sleep_mock,
    ):
        """run should log task exceptions and continue with remaining tasks."""
        scheduler_main = Main()
        scheduler_main.kill_signal.received = False

        update_task = MagicMock(name="UpdateJobsStatuses")
        update_task.name = "UpdateJobsStatuses"
        update_task.task.side_effect = RuntimeError("boom")

        free_task = MagicMock(name="FreeResources")

        def stop_loop():
            scheduler_main.kill_signal.received = True

        schedule_task = MagicMock(name="ScheduleQueuedJobs")
        schedule_task.task.side_effect = stop_loop

        update_jobs_statuses_cls.return_value = update_task
        free_resources_cls.return_value = free_task
        schedule_queued_jobs_cls.return_value = schedule_task

        scheduler_main.run()

        logger.exception.assert_called_once()
        free_task.task.assert_called_once_with()
        schedule_task.task.assert_called_once_with()
        sleep_mock.assert_not_called()
        logger.info.assert_called_once_with("Scheduler loop stopped.")
