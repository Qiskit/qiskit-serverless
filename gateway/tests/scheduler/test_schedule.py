"""Tests scheduling."""

import uuid
from collections import deque
from unittest.mock import MagicMock, patch

from core.services.runners.ray_runner import FilteredLogs
from prometheus_client import CollectorRegistry

import pytest
from django.core.management import call_command
from django.test import override_settings
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase

from core.model_managers.job_events import JobEventContext
from core.config_key import ConfigKey
from core.models import Config, Job, ComputeResource, JobEvent, Program
from core.domain.exceptions.invalid_job_transition_exception import InvalidJobTransitionException
from core.services.runners import RunnerError, RunnerRetryableError
from core.services.storage import get_logs_storage

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

from scheduler.schedule import (
    _REFUSED_CANCEL_WARNED,
    CodeEngineBreakers,
    first_cancel_refusal,
    FleetsJobCanceller,
    FleetsJobSubmitter,
    get_jobs_to_schedule_fair_share,
    execute_ray_job,
)
from scheduler.tasks.update_ray_jobs_statuses import UpdateRayJobsStatuses

from tests.utils import TestUtils


def _open_breakers_after_one_failure():
    Config.add_defaults()
    Config.set(ConfigKey.FLEETS_BREAKER_FAILURES, "1")


class TestScheduleApi(APITestCase):
    """TestScheduleApi."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        settings.MEDIA_ROOT = str(tmp_path)

    def test_get_fair_share_jobs(self):
        """Tests fair share jobs getter function."""

        # Create test data to match fixture expectations (7 jobs total)
        test_user = TestUtils.get_user_and_username("test_user")[0]
        test2_user = TestUtils.get_user_and_username("test2_user")[0]
        test3_user = TestUtils.get_user_and_username("test3_user")[0]
        test4_user = TestUtils.get_user_and_username("test4_user")[0]

        program = TestUtils.create_program(program_title="Program", author=test_user)
        compute_resource = TestUtils.get_or_create_compute_resource(
            title="compute resource", host="somehost", owner=test3_user
        )

        # Create 7 jobs with various statuses
        job1 = TestUtils.create_job(author=test_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test2_user, program=program, status=Job.PENDING, result='{"somekey":1}')
        TestUtils.create_job(
            author=test3_user,
            program=program,
            status=Job.PENDING,
            compute_resource=compute_resource,
            result='{"somekey":1}',
        )
        TestUtils.create_job(author=test3_user, program=program, status=Job.RUNNING, result='{"somekey":1}')
        job6 = TestUtils.create_job(author=test4_user, program=program, status=Job.QUEUED, result='{"somekey":1}')
        TestUtils.create_job(author=test4_user, program=program, status=Job.QUEUED, result='{"somekey":1}')

        jobs = get_jobs_to_schedule_fair_share(5, False)

        for job in jobs:
            assert isinstance(job, Job)

        author_ids = [job.author_id for job in jobs]
        job_ids = [str(job.id) for job in jobs]
        assert 1 in author_ids
        assert 4 in author_ids
        assert len(jobs) == 2
        assert str(job1.id) in job_ids  # `test4_user` job
        assert str(job6.id) in job_ids  # `test_user` job

    @override_settings(LIMITS_JOBS_PER_USER=2, LIMITS_JOBS_PER_USER_FLEETS=2)
    def test_fair_share_per_user_limit_is_runner_scoped(self):
        """A user's Ray and Fleets running jobs are counted independently.

        With LIMITS_JOBS_PER_USER=2, a user with 2 running Ray jobs is at the Ray
        cap but must still be schedulable for Fleets, because Fleets has its own,
        separate per-user tally and limit.
        """
        user = TestUtils.get_user_and_username("mixed_user")[0]
        program = TestUtils.create_program(program_title="Program", author=user)

        # 2 running Ray jobs -> user is at the Ray cap.
        TestUtils.create_job(author=user, program=program, status=Job.RUNNING, runner=Program.RAY)
        TestUtils.create_job(author=user, program=program, status=Job.RUNNING, runner=Program.RAY)
        # 1 queued Fleets job -> should NOT be blocked by the Ray running jobs.
        fleets_job = TestUtils.create_job(author=user, program=program, status=Job.QUEUED, runner=Program.FLEETS)

        fleets_jobs = get_jobs_to_schedule_fair_share(slots=5, gpu=False, runner=Program.FLEETS)

        assert fleets_job in fleets_jobs

    @override_settings(LIMITS_JOBS_PER_USER=2, LIMITS_JOBS_PER_USER_FLEETS=5)
    def test_fair_share_uses_fleets_specific_limit(self):
        """Fleets scheduling uses LIMITS_JOBS_PER_USER_FLEETS, not LIMITS_JOBS_PER_USER."""
        user = TestUtils.get_user_and_username("fleets_heavy_user")[0]
        program = TestUtils.create_program(program_title="Program", author=user)

        # 3 running Fleets jobs: over the Ray limit (2) but under the Fleets limit (5).
        for _ in range(3):
            TestUtils.create_job(author=user, program=program, status=Job.RUNNING, runner=Program.FLEETS)
        fleets_job = TestUtils.create_job(author=user, program=program, status=Job.QUEUED, runner=Program.FLEETS)

        fleets_jobs = get_jobs_to_schedule_fair_share(slots=5, gpu=False, runner=Program.FLEETS)

        assert fleets_job in fleets_jobs

    @override_settings(LIMITS_JOBS_PER_USER_FLEETS=2)
    def test_fair_share_ignores_filler_jobs_in_the_per_user_tally(self):
        """Filler jobs are not user demand, so they must not use up their author's cap."""
        user = TestUtils.get_user_and_username("filler_function_owner")[0]
        program = TestUtils.create_program(program_title="Program", author=user)

        # Enough filler jobs to put the author over the cap on their own.
        for _ in range(3):
            TestUtils.create_job(author=user, program=program, status=Job.RUNNING, runner=Program.FLEETS, filler=True)
        real_job = TestUtils.create_job(author=user, program=program, status=Job.QUEUED, runner=Program.FLEETS)

        fleets_jobs = get_jobs_to_schedule_fair_share(slots=5, gpu=False, runner=Program.FLEETS)

        assert real_job in fleets_jobs

    @patch("scheduler.schedule.get_runner")
    def test_execute_ray_job_success(self, mock_get_runner_client):
        """Tests successful Ray job execution via runner.submit()."""
        mock_compute_resource = MagicMock(spec=ComputeResource)
        mock_compute_resource.title = "test-cluster"
        mock_compute_resource.pk = None

        mock_runner = MagicMock()
        mock_get_runner_client.return_value = mock_runner

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""
        job.compute_resource = mock_compute_resource

        ret_job = execute_ray_job(job)

        mock_runner.submit.assert_called_once()
        mock_compute_resource.save.assert_called_once()
        assert ret_job.status == Job.PENDING
        assert ret_job.env_vars == "{}"

    @patch("scheduler.schedule.get_runner")
    def test_execute_ray_job_failure(self, mock_get_runner_client):
        """Tests Ray job execution failure handling."""
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RunnerError("Submit failed")
        mock_get_runner_client.return_value = mock_runner

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ret_job = execute_ray_job(job)

        mock_runner.submit.assert_called_once()
        assert ret_job.status == Job.FAILED
        assert ret_job.env_vars == "{}"

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_success(self, mock_trace, mock_get_runner_client):
        """Tests successful Fleets job execution via runner.submit()."""
        mock_runner = MagicMock()
        mock_get_runner_client.return_value = mock_runner
        transitions = MagicMock()

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ctx = MagicMock()
        ret_job = FleetsJobSubmitter(transitions).submit(job, ctx)

        mock_runner.submit.assert_called_once()
        assert ret_job.status == Job.PENDING
        assert ret_job.env_vars == "{}"
        transitions.queued_to_pending.assert_called_once()
        assert transitions.queued_to_pending.call_args.kwargs["job_fields"]["env_vars"] == "{}"
        transitions.to_failed.assert_not_called()

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_failure(self, mock_trace, mock_get_runner_client):
        """Tests Fleets job execution failure handling."""
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RunnerError("Submit failed")
        mock_get_runner_client.return_value = mock_runner
        transitions = MagicMock()

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ctx = MagicMock()
        ret_job = FleetsJobSubmitter(transitions).submit(job, ctx)

        mock_runner.submit.assert_called_once()
        assert ret_job.status == Job.FAILED
        assert ret_job.env_vars == "{}"
        transitions.to_failed.assert_called_once()
        assert transitions.to_failed.call_args.kwargs["job_fields"]["env_vars"] == "{}"
        transitions.queued_to_pending.assert_not_called()

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_leaves_the_job_untouched_when_code_engine_is_unavailable(
        self, mock_trace, mock_get_runner_client
    ):
        Config.add_defaults()
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RunnerRetryableError("Too Many Requests")
        mock_get_runner_client.return_value = mock_runner
        transitions = MagicMock()

        job = MagicMock()
        job.status = Job.QUEUED
        job.env_vars = '{"KEY": "value"}'

        with pytest.raises(RunnerRetryableError):
            FleetsJobSubmitter(transitions).submit(job, MagicMock())

        assert job.status == Job.QUEUED
        assert job.env_vars == '{"KEY": "value"}'
        transitions.queued_to_pending.assert_not_called()
        transitions.to_failed.assert_not_called()

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_skips_code_engine_once_the_breaker_opens(self, mock_trace, mock_get_runner_client):
        _open_breakers_after_one_failure()
        mock_get_runner_client.return_value.submit.side_effect = RunnerRetryableError("Too Many Requests")

        submitter = FleetsJobSubmitter(MagicMock())

        with pytest.raises(RunnerRetryableError):
            submitter.submit(MagicMock(ce_region="us-east"), MagicMock())
        with pytest.raises(RunnerRetryableError):
            submitter.submit(MagicMock(ce_region="us-east"), MagicMock())

        mock_get_runner_client.return_value.submit.assert_called_once()

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_reaches_code_engine_again_once_the_pause_is_over(self, mock_trace, mock_get_runner_client):
        _open_breakers_after_one_failure()
        Config.set(ConfigKey.FLEETS_BREAKER_PAUSE_SECONDS, "60")
        runner = mock_get_runner_client.return_value
        runner.submit.side_effect = RunnerRetryableError("Too Many Requests")
        submitter = FleetsJobSubmitter(MagicMock())

        with patch("scheduler.tasks.circuit_breaker.time.monotonic", return_value=1000.0):
            with pytest.raises(RunnerRetryableError):
                submitter.submit(MagicMock(ce_region="us-east"), MagicMock())
            assert submitter.paused("us-east") is True

        runner.submit.side_effect = None
        with patch("scheduler.tasks.circuit_breaker.time.monotonic", return_value=1061.0):
            assert submitter.paused("us-east") is False
            submitter.submit(MagicMock(ce_region="us-east"), MagicMock())

        assert runner.submit.call_count == 2

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_does_not_count_a_failed_job_against_the_breaker(self, mock_trace, mock_get_runner_client):
        _open_breakers_after_one_failure()
        mock_get_runner_client.return_value.submit.side_effect = RunnerError("Bad Request")

        submitter = FleetsJobSubmitter(MagicMock())

        submitter.submit(MagicMock(ce_region="us-east"), MagicMock())

        assert submitter.paused("us-east") is False

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_pauses_only_the_region_that_failed(self, mock_trace, mock_get_runner_client):
        _open_breakers_after_one_failure()
        runner = mock_get_runner_client.return_value
        runner.submit.side_effect = RunnerRetryableError("Too Many Requests")
        submitter = FleetsJobSubmitter(MagicMock())

        with pytest.raises(RunnerRetryableError):
            submitter.submit(MagicMock(ce_region="us-east"), MagicMock())
        runner.submit.side_effect = None
        submitter.submit(MagicMock(ce_region="eu-de"), MagicMock())

        assert submitter.paused("us-east") is True
        assert submitter.paused("eu-de") is False
        assert runner.submit.call_count == 2

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_does_not_raise_when_the_job_already_turned_terminal(
        self, mock_trace, mock_get_runner_client
    ):
        """Lost the race: something else (e.g. a user-initiated stop) already moved the job to
        a terminal status while it was being submitted. The transition raises
        InvalidJobTransitionException; this must not propagate and crash the scheduler tick."""
        mock_runner = MagicMock()
        mock_get_runner_client.return_value = mock_runner
        transitions = MagicMock()
        transitions.queued_to_pending.side_effect = InvalidJobTransitionException(
            "Job x: invalid transition STOPPED -> PENDING"
        )

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ctx = MagicMock()
        ret_job = FleetsJobSubmitter(transitions).submit(job, ctx)  # must not raise

        assert ret_job.status == Job.PENDING

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_does_not_raise_when_a_failed_submit_lost_the_race(self, mock_trace, mock_get_runner_client):
        """Same race when the submit failed: the job is returned as FAILED, like the caller expects."""
        mock_runner = MagicMock()
        mock_runner.submit.side_effect = RunnerError("Submit failed")
        mock_get_runner_client.return_value = mock_runner
        transitions = MagicMock()
        transitions.to_failed.side_effect = InvalidJobTransitionException("Job x: invalid transition STOPPED -> FAILED")

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        ret_job = FleetsJobSubmitter(transitions).submit(job, MagicMock())  # must not raise

        assert ret_job.status == Job.FAILED

    @patch("scheduler.schedule.get_runner")
    @patch("scheduler.schedule.trace")
    def test_fleets_submit_returns_the_status_it_ended_with_when_the_transition_fails(
        self, mock_trace, mock_get_runner_client
    ):
        """A failing transition propagates, but the job already carries the status the submit ended with:
        the filler balancer reads it to tell 'raised before runner.submit()' from 'raised after'."""
        mock_get_runner_client.return_value.submit.side_effect = RunnerError("Submit failed")
        transitions = MagicMock()
        transitions.to_failed.side_effect = RuntimeError("db down")

        job = MagicMock()
        job.status = Job.QUEUED
        job.logs = ""

        with pytest.raises(RuntimeError, match="db down"):
            FleetsJobSubmitter(transitions).submit(job, MagicMock())

        assert job.status == Job.FAILED

    @patch("scheduler.tasks.update_ray_jobs_statuses.get_runner")
    def test_job_runtime_limit(self, get_runner):
        """Tests job runtime limit enforcement.

        This test verifies that UpdateJobStatuses correctly identifies jobs
        that have exceeded the PROGRAM_TIMEOUT setting.
        """
        runner = MagicMock()
        runner.status.return_value = JobStatus.RUNNING
        runner.logs.return_value = FilteredLogs(
            public_logs=deque(["No logs yet.", "Maximum job runtime reached. Stopping the job."]),
            private_logs=None,
        )
        get_runner.return_value = runner

        # Override PROGRAM_TIMEOUT to 0 hours so job immediately exceeds limit
        with self.settings(PROGRAM_TIMEOUT=0):
            # Create test user and authenticate
            user = TestUtils.authorize_client(user="test_limit_user", client=self.client)

            # Create a private program for the job. If provider is given, the public logs will be empty.
            program = TestUtils.create_program(
                program_title="Timeout-Test-Program",
                author=user,
            )

            compute_resource = ComputeResource.objects.create(title="test-cluster-test-job-id", active=True)
            # Create a job with RUNNING status
            # TestUtils.create_job automatically creates a JobEvent with current timestamp for creation and add a
            # JobEvent with change STATUS_CHANGE because the status is not Job.QUEUED.
            job = TestUtils.create_job(
                author=user, status=Job.RUNNING, program=program, compute_resource=compute_resource
            )
            job_event = JobEvent.objects.filter(job=job).first()

            # Job status is RUNNING.
            assert job_event.data["status"] == Job.RUNNING

            # Running job status update which verify that will change the job status (timeout exceeded)
            # Since PROGRAM_TIMEOUT=0, any job with a JobEvent will have exceeded the limit
            UpdateRayJobsStatuses(kill_signal=KillSignal(), metrics=SchedulerMetrics(CollectorRegistry())).run()
            job.refresh_from_db()
            job_event = JobEvent.objects.filter(job=job).first()

            assert job_event.data["status"] == Job.STOPPED
            # Since the job is in terminal state, its `logs` attribute instance is empty.
            # We need to check the logs in storage
            assert (
                "Maximum job runtime reached" in get_logs_storage(job).get_public_logs()
            ), "Job logs should contain timeout message"

            job_events = JobEvent.objects.filter(job=job).order_by("created")
            # The table was filled as following: Job creation, Job status change to running, job stopping
            # due exceeding time limit.
            assert len(job_events) == 3


def test_fleets_submit_records_the_given_event_context():
    """The JobEvent context is the caller's, defaulting to SCHEDULE_JOBS."""
    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()

    transitions = MagicMock()
    with patch("scheduler.schedule.get_runner"):
        FleetsJobSubmitter(transitions).submit(mock_job, None, context=JobEventContext.FILLER_SUBMIT)

    assert transitions.queued_to_pending.call_args.kwargs["context"] is JobEventContext.FILLER_SUBMIT


def test_fleets_submit_defaults_to_the_schedule_jobs_context():
    """Callers that pass no context still record SCHEDULE_JOBS."""
    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()

    transitions = MagicMock()
    with patch("scheduler.schedule.get_runner"):
        FleetsJobSubmitter(transitions).submit(mock_job, None)

    assert transitions.queued_to_pending.call_args.kwargs["context"] is JobEventContext.SCHEDULE_JOBS


class TestFirstCancelRefusal:
    """Both scheduler callers ask again every tick, so a refusal must report once, not once a second."""

    @pytest.fixture(autouse=True)
    def _clear_warned(self):
        _REFUSED_CANCEL_WARNED.clear()
        yield
        _REFUSED_CANCEL_WARNED.clear()

    def test_only_the_first_refusal_reports(self):
        job = MagicMock(id="job-refused")

        assert [first_cancel_refusal(job) for _ in range(3)] == [True, False, False]

    def test_the_warned_set_is_bounded(self):
        with patch("scheduler.schedule._REFUSED_CANCEL_LIMIT", 2):
            for index in range(3):
                first_cancel_refusal(MagicMock(id=f"job-{index}"))

        assert len(_REFUSED_CANCEL_WARNED) == 1


@pytest.mark.django_db
class TestFleetsJobCanceller:
    """The scheduler's cancel: one try, and the region's breaker decides when to try again."""

    @staticmethod
    def _canceller(side_effect=None, returns=True, breakers=None):
        transitions = MagicMock()
        if side_effect is not None:
            transitions.try_stop.side_effect = side_effect
        else:
            transitions.try_stop.return_value = returns
        return FleetsJobCanceller(transitions, breakers), transitions

    def test_a_cancel_that_landed_returns_what_try_stop_returned(self):
        canceller, transitions = self._canceller(returns=True)
        job = MagicMock(ce_region="us-east")

        assert canceller.cancel(job, context=JobEventContext.UPDATE_JOB_STATUS) is True
        assert canceller.paused("us-east") is False
        transitions.try_stop.assert_called_once()

    def test_a_cancel_that_lands_lets_a_later_refusal_report_again(self):
        """Without the discard the set only ever grows, and a job that recovers stays silenced."""
        canceller, _ = self._canceller(returns=True)
        job = MagicMock(ce_region="us-east")
        _REFUSED_CANCEL_WARNED.add(str(job.id))

        canceller.cancel(job, context=JobEventContext.UPDATE_JOB_STATUS)

        assert str(job.id) not in _REFUSED_CANCEL_WARNED

    def test_nothing_to_cancel_counts_as_an_answer_from_code_engine(self):
        """False is Code Engine's own 404 or 409, so the region is answering."""
        _open_breakers_after_one_failure()
        canceller, _ = self._canceller(returns=False)

        assert canceller.cancel(MagicMock(ce_region="us-east"), context=JobEventContext.UPDATE_JOB_STATUS) is False
        assert canceller.paused("us-east") is False

    def test_a_job_with_no_fleet_teaches_the_breaker_nothing(self):
        """No call is made, so this must not count as the region answering and clear the streak."""
        Config.add_defaults()
        Config.set(ConfigKey.FLEETS_BREAKER_FAILURES, "2")
        breakers = CodeEngineBreakers()
        canceller, transitions = self._canceller(
            side_effect=RunnerRetryableError("Too Many Requests"), breakers=breakers
        )
        job = MagicMock(ce_region="us-east", fleet_id="fleet-1")
        no_fleet = MagicMock(ce_region="us-east", fleet_id=None)

        with pytest.raises(RunnerRetryableError):
            canceller.cancel(job, context=JobEventContext.UPDATE_JOB_STATUS)
        assert canceller.cancel(no_fleet, context=JobEventContext.UPDATE_JOB_STATUS) is False
        with pytest.raises(RunnerRetryableError):
            canceller.cancel(job, context=JobEventContext.UPDATE_JOB_STATUS)

        assert canceller.paused("us-east") is True
        assert transitions.try_stop.call_count == 2

    def test_an_undeliverable_cancel_counts_against_the_region_breaker(self):
        _open_breakers_after_one_failure()
        canceller, _ = self._canceller(side_effect=RunnerRetryableError("Too Many Requests"))

        with pytest.raises(RunnerRetryableError):
            canceller.cancel(MagicMock(ce_region="us-east"), context=JobEventContext.UPDATE_JOB_STATUS)

        assert canceller.paused("us-east") is True

    def test_a_refused_cancel_leaves_the_breaker_closed(self):
        """A request Code Engine refused says nothing about whether the region is answering."""
        _open_breakers_after_one_failure()
        canceller, _ = self._canceller(side_effect=RunnerError("Forbidden"))

        with pytest.raises(RunnerError):
            canceller.cancel(MagicMock(ce_region="us-east"), context=JobEventContext.UPDATE_JOB_STATUS)

        assert canceller.paused("us-east") is False

    def test_an_open_breaker_sends_no_cancel(self):
        _open_breakers_after_one_failure()
        canceller, transitions = self._canceller(side_effect=RunnerRetryableError("Too Many Requests"))

        for _ in range(2):
            with pytest.raises(RunnerRetryableError):
                canceller.cancel(MagicMock(ce_region="us-east"), context=JobEventContext.UPDATE_JOB_STATUS)

        transitions.try_stop.assert_called_once()

    def test_a_failed_cancel_pauses_the_submit_in_the_same_region_only(self):
        """A region answers the same way to both, so one breaker holds the fact for the whole region."""
        _open_breakers_after_one_failure()
        breakers = CodeEngineBreakers()
        canceller, transitions = self._canceller(
            side_effect=RunnerRetryableError("Too Many Requests"), breakers=breakers
        )
        submitter = FleetsJobSubmitter(transitions, breakers)

        with pytest.raises(RunnerRetryableError):
            canceller.cancel(MagicMock(ce_region="us-east"), context=JobEventContext.UPDATE_JOB_STATUS)

        assert submitter.paused("us-east") is True
        assert submitter.paused("eu-de") is False
