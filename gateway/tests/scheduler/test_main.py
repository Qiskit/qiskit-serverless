"""Unit tests for the scheduler main service and its loops."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from django.db.utils import OperationalError
from prometheus_client import CollectorRegistry

from scheduler.health import UNHEALTHY_THRESHOLD
from core.services.background_executor import (
    BackgroundExecutorNotInitializedError,
    BackgroundPool,
    get_background_executor,
)
from core.services.workload_best_effort_mirror import WorkloadBackgroundMirror
from scheduler.loop import SchedulerLoop
from scheduler.main import Main
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.balance_filler_jobs import BalanceFillerJobs
from scheduler.tasks.export_fleets_breakers import ExportFleetsBreakers
from scheduler.tasks.free_fleets_resources import FreeFleetsResources
from scheduler.tasks.free_ray_resources import FreeRayResources
from scheduler.tasks.outbox import OutboxTask
from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs
from scheduler.tasks.schedule_ray_jobs import ScheduleRayJobs
from scheduler.tasks.stop_blocked_fleets_jobs import StopBlockedFleetsJobs
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses
from scheduler.tasks.update_ray_jobs_statuses import UpdateRayJobsStatuses
from scheduler.views.probes import make_liveness

# Scheduler and Gateway share the same settings and the same SITE_HOST value. We need to override it
# during tests to avoid collisions

SITE_HOST = "http://127.0.0.1:8200"


def fake_task(name="fake_task", run=None):
    """A task that does what ``run`` says, and counts its calls."""
    task = MagicMock()
    task.name = name
    if run:
        task.run.side_effect = run
    return task


class TestMain:
    """Tests for scheduler Main service."""

    @pytest.fixture(autouse=True)
    def _setup(self, settings, db):
        settings.SITE_HOST = SITE_HOST
        self.scheduler_main = Main(metrics=SchedulerMetrics(CollectorRegistry()))
        yield
        self.scheduler_main.stop_http_server()

    def use_loops(self, *loops):
        """Replace the real loops, which would call Code Engine and COS, with the ones of the test."""
        self.scheduler_main.loops = list(loops)

    def make_loop(self, name, tasks):
        main = self.scheduler_main
        return SchedulerLoop(name, tasks, main.kill_signal, main.metrics, main.health)

    @property
    def tasks(self):
        return [task for loop in self.scheduler_main.loops for task in loop.tasks]

    def task_of(self, task_type):
        return next(task for task in self.tasks if isinstance(task, task_type))

    def loop_of(self, task_type):
        return next(
            loop.name for loop in self.scheduler_main.loops if any(isinstance(t, task_type) for t in loop.tasks)
        )

    def test_run_opens_the_background_executor_and_closes_it_when_it_ends(self):
        main = self.scheduler_main
        accepted = []

        def submit_then_stop():
            accepted.append(get_background_executor().submit(BackgroundPool.RUNTIME_API, lambda: None) is not None)
            main.kill_signal.received = True

        self.use_loops(self.make_loop("only", [fake_task(run=submit_then_stop)]))

        main.run()

        assert accepted == [True]
        with pytest.raises(BackgroundExecutorNotInitializedError):
            get_background_executor().submit(BackgroundPool.RUNTIME_API, lambda: None)

    def test_every_loop_runs_in_its_own_thread_and_not_in_the_main_one(self):
        main = self.scheduler_main
        threads = {}
        started = threading.Barrier(2, timeout=10)

        def record(name):
            def run():
                threads[name] = threading.current_thread()
                # waits for the other loop, so it can only pass if both run at the same time
                started.wait()
                main.kill_signal.received = True

            return run

        self.use_loops(
            self.make_loop("one", [fake_task("task_one", run=record("one"))]),
            self.make_loop("two", [fake_task("task_two", run=record("two"))]),
        )

        main.run()

        assert set(threads) == {"one", "two"}
        assert threads["one"] is not threads["two"]
        assert threading.current_thread() not in threads.values()

    def test_a_slow_task_does_not_delay_the_tasks_of_another_loop(self):
        main = self.scheduler_main
        release_slow = threading.Event()
        fast_runs = []
        slow_released = []

        def fast():
            fast_runs.append(1)
            if len(fast_runs) >= 3:
                release_slow.set()

        def slow():
            # only returns once the other loop has gone round three times, and gives up instead of hanging the suite
            slow_released.append(release_slow.wait(timeout=10))
            main.kill_signal.received = True

        self.use_loops(
            self.make_loop("slow", [fake_task("slow", run=slow)]),
            self.make_loop("fast", [fake_task("fast", run=fast)]),
        )
        with patch("scheduler.loop.MIN_ITERATION_SECONDS", 0.01):
            main.run()

        assert slow_released == [True]
        assert len(fast_runs) >= 3

    def test_the_tasks_of_a_loop_run_in_order(self):
        main = self.scheduler_main
        order = []

        def stop():
            order.append("last")
            main.kill_signal.received = True

        self.use_loops(
            self.make_loop(
                "ordered",
                [
                    fake_task("first", run=lambda: order.append("first")),
                    fake_task("second", run=lambda: order.append("second")),
                    fake_task("third", run=stop),
                ],
            )
        )

        main.run()

        assert order == ["first", "second", "last"]

    def test_the_fleets_status_update_runs_alone_in_its_loop(self):
        update = next(loop for loop in self.scheduler_main.loops if loop.name == "fleets-update")

        assert [type(task) for task in update.tasks] == [UpdateFleetsJobsStatuses]

    def test_each_task_is_in_the_loop_of_its_engine_or_in_maintenance(self):
        expected = {
            ScheduleRayJobs: "ray",
            UpdateRayJobsStatuses: "ray",
            FreeRayResources: "ray",
            ScheduleFleetsJobs: "fleets-schedule",
            StopBlockedFleetsJobs: "fleets-schedule",
            BalanceFillerJobs: "fleets-schedule",
            UpdateFleetsJobsStatuses: "fleets-update",
            OutboxTask: "maintenance",
            FreeFleetsResources: "maintenance",
            ExportFleetsBreakers: "maintenance",
        }

        assert {task_type: self.loop_of(task_type) for task_type in expected} == expected

    def test_the_breakers_are_exported_last_of_the_maintenance_loop(self):
        maintenance = next(loop for loop in self.scheduler_main.loops if loop.name == "maintenance")

        assert isinstance(maintenance.tasks[-1], ExportFleetsBreakers)

    def test_every_task_has_a_distinct_name(self):
        """The task metrics are labeled by task name only, so two tasks with one name would add up."""
        names = [task.name for task in self.tasks]

        assert len(names) == len(set(names))

    def test_the_tasks_that_change_a_job_status_share_one_transition_service(self):
        """One service, so the Kafka producers of its sender are created once for the whole scheduler."""
        sharing = (UpdateFleetsJobsStatuses, BalanceFillerJobs)
        tasks = [task for task in self.tasks if isinstance(task, sharing)]
        submitters = [task.submitter for task in self.tasks if isinstance(task, ScheduleFleetsJobs)]

        assert len(tasks) == len(sharing)
        assert len({id(task.transitions) for task in tasks} | {id(s.transitions) for s in submitters}) == 1

    def test_the_shared_transition_service_mirrors_the_intermediate_statuses(self):
        task = self.task_of(UpdateFleetsJobsStatuses)

        assert isinstance(task.transitions.workload_mirror, WorkloadBackgroundMirror)

    def test_the_tasks_that_submit_fleets_jobs_share_one_submitter(self):
        sharing = (ScheduleFleetsJobs, BalanceFillerJobs)
        tasks = [task for task in self.tasks if isinstance(task, sharing)]

        assert len(tasks) == len(sharing)
        assert len({id(task.submitter) for task in tasks}) == 1

    def test_the_tasks_that_call_code_engine_share_one_fleets_breakers(self):
        sharing = (UpdateFleetsJobsStatuses, BalanceFillerJobs, StopBlockedFleetsJobs)
        submitters = [task.submitter for task in self.tasks if isinstance(task, ScheduleFleetsJobs)]
        cancellers = [task.canceller for task in self.tasks if isinstance(task, sharing)]
        deleters = [task.deleter for task in self.tasks if isinstance(task, FreeFleetsResources)]
        exporters = [task for task in self.tasks if isinstance(task, ExportFleetsBreakers)]

        assert submitters and len(cancellers) == len(sharing) and len(deleters) == 1 and len(exporters) == 1
        assert len({id(owner.breakers) for owner in submitters + cancellers + deleters + exporters}) == 1

    def test_run_executes_tasks(self):
        """run should execute tasks and stop when kill signal is received."""
        called = False

        def run_side_effect():
            nonlocal called
            called = True
            self.scheduler_main.kill_signal.received = True

        task = fake_task(run=run_side_effect)

        self.use_loops(self.make_loop("only", [task]))
        self.scheduler_main.run()

        assert called is True
        assert task.run.call_count == 1

    def test_each_loop_runs_the_per_request_connection_check(self):
        task = fake_task(run=lambda: setattr(self.scheduler_main.kill_signal, "received", True))
        self.use_loops(self.make_loop("only", [task]))

        with patch("scheduler.loop.close_old_connections") as close_old:
            self.scheduler_main.run()

        close_old.assert_called_once_with()

    def test_every_task_is_closed_once_the_loops_finish(self):
        """So the Kafka consumers leave their groups instead of holding partitions after shutdown."""
        first = fake_task(run=lambda: setattr(self.scheduler_main.kill_signal, "received", True))
        second = fake_task("second")

        self.use_loops(self.make_loop("one", [first]), self.make_loop("two", [second]))
        self.scheduler_main.run()

        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_a_task_that_fails_to_close_does_not_keep_the_others_open(self):
        failing = fake_task("failing")
        failing.close.side_effect = RuntimeError("close failed")
        other = fake_task("other")
        self.scheduler_main.kill_signal.received = True

        self.use_loops(self.make_loop("only", [failing, other]))
        self.scheduler_main.run()

        other.close.assert_called_once()

    def test_task_fails(self):
        """When a task raises, metrics.increase_task_error should be called, and the next task still runs."""
        failing_task = fake_task("failing_task")
        failing_task.run.side_effect = Exception("boom")
        stop_task = fake_task(run=lambda: setattr(self.scheduler_main.kill_signal, "received", True))

        self.scheduler_main.metrics = MagicMock()
        self.use_loops(
            SchedulerLoop(
                "only",
                [failing_task, stop_task],
                self.scheduler_main.kill_signal,
                self.scheduler_main.metrics,
                self.scheduler_main.health,
            )
        )

        self.scheduler_main.run()

        self.scheduler_main.metrics.increase_task_error.assert_called_once()
        task_name, error = self.scheduler_main.metrics.increase_task_error.call_args[0]
        assert task_name == "failing_task"
        assert str(error) == "boom"
        stop_task.run.assert_called_once()

    def test_http_server_starts_and_stops(self):
        """HTTP server should start and stop after the loops end."""
        self.scheduler_main.start_http_server()
        # kill_signal to True makes the loops exit immediately
        self.scheduler_main.kill_signal.received = True
        self.use_loops()
        self.scheduler_main.run()
        assert self.scheduler_main.http_server.is_running() is False

    def test_loop_iteration_records_metrics_with_the_name_of_the_loop(self):
        """Each loop iteration should call observe_scheduler_iteration, labeled with its loop."""
        self.scheduler_main.metrics = MagicMock()
        task = fake_task(run=lambda: setattr(self.scheduler_main.kill_signal, "received", True))
        self.use_loops(
            SchedulerLoop(
                "named",
                [task],
                self.scheduler_main.kill_signal,
                self.scheduler_main.metrics,
                self.scheduler_main.health,
            )
        )

        self.scheduler_main.run()

        self.scheduler_main.metrics.observe_scheduler_iteration.assert_called_once()
        loop, elapsed = self.scheduler_main.metrics.observe_scheduler_iteration.call_args[0]
        assert loop == "named"
        assert elapsed >= 0

    def test_loop_duration_does_not_depend_on_the_wall_clock(self):
        """A wall clock jump of one hour during the tick must not show up in the observed durations."""
        wall_clock = [1_000_000.0]

        def jump_and_stop():
            wall_clock[0] += 3600
            self.scheduler_main.kill_signal.received = True

        self.scheduler_main.metrics = MagicMock()
        task = fake_task("jumpy", run=jump_and_stop)
        self.use_loops(
            SchedulerLoop(
                "only",
                [task],
                self.scheduler_main.kill_signal,
                self.scheduler_main.metrics,
                self.scheduler_main.health,
            )
        )

        with patch("time.time", side_effect=lambda: wall_clock[0]):
            self.scheduler_main.run()

        _, elapsed = self.scheduler_main.metrics.observe_scheduler_iteration.call_args[0]
        _, task_elapsed = self.scheduler_main.metrics.observe_task_duration.call_args[0]
        assert elapsed < 60
        assert task_elapsed < 60

    def test_a_stop_request_wakes_a_sleeping_loop_up(self):
        """A quick loop sleeps up to MIN_ITERATION_SECONDS between iterations, and the stop must not wait for that."""
        main = self.scheduler_main
        iterated = threading.Event()
        task = fake_task(run=iterated.set)
        loop = self.make_loop("quick", [task])

        with patch("scheduler.loop.MIN_ITERATION_SECONDS", 30):
            loop.start()
            assert iterated.wait(timeout=10)
            # the loop has run its task and is now parked in a 30 second sleep
            started = time.monotonic()
            main.kill_signal.received = True
            loop.join()
            woke_after = time.monotonic() - started

        assert not loop.is_alive()
        assert woke_after < 5

    def test_the_scheduler_stops_with_an_error_when_a_loop_dies(self):
        """A dead loop is not coming back, so the process must exit and be restarted instead of running without it."""
        main = self.scheduler_main
        main.metrics = MagicMock()
        main.metrics.observe_scheduler_iteration.side_effect = RuntimeError("metrics broke")
        self.use_loops(SchedulerLoop("doomed", [fake_task()], main.kill_signal, main.metrics, main.health))

        with pytest.raises(RuntimeError, match="doomed"):
            main.run()

        assert main.kill_signal.received is True

    def test_liveness_unhealthy_after_db_errors(self):
        """After UNHEALTHY_THRESHOLD consecutive DB errors, liveness should return 503."""
        call_count = 0

        def db_error_then_stop():
            nonlocal call_count
            call_count += 1
            if call_count >= UNHEALTHY_THRESHOLD:
                self.scheduler_main.kill_signal.received = True
            raise OperationalError("connection lost")

        failing_task = fake_task("db_failing_task", run=db_error_then_stop)

        self.scheduler_main.metrics = MagicMock()
        self.use_loops(
            SchedulerLoop(
                "only",
                [failing_task],
                self.scheduler_main.kill_signal,
                self.scheduler_main.metrics,
                self.scheduler_main.health,
            )
        )
        with patch("scheduler.loop.MIN_ITERATION_SECONDS", 0.01):
            self.scheduler_main.run()

        assert self.scheduler_main.metrics.increase_task_error.call_count == UNHEALTHY_THRESHOLD
        assert self.scheduler_main.metrics.increase_task_error.call_args[0][0] == "db_failing_task"

        liveness = make_liveness(self.scheduler_main.health)
        response = liveness(MagicMock())
        assert response.status_code == 503

    def test_a_healthy_loop_does_not_hide_the_db_errors_of_another_one(self):
        """The streak is per loop: a loop that works must not reset the one of a loop that cannot reach the DB."""
        health = self.scheduler_main.health

        for _ in range(UNHEALTHY_THRESHOLD):
            health.set_db_error("broken")
            health.clear_db_error("healthy")

        assert health.is_unhealthy is True

    def test_a_loop_that_dies_makes_the_scheduler_unhealthy(self):
        """Nothing restarts a dead loop, so the liveness probe has to ask for a restart of the pod."""
        main = self.scheduler_main
        main.metrics = MagicMock()
        # the metrics call is outside the per-task handling, so raising there kills the thread of the loop
        main.metrics.observe_scheduler_iteration.side_effect = RuntimeError("metrics broke")
        loop = SchedulerLoop("doomed", [fake_task()], main.kill_signal, main.metrics, main.health)

        loop.start()
        loop.join()

        assert main.health.is_unhealthy is True
