"""Tests for BalanceFillerJobs.

These run against a real database because the whole point of the task is its
queries: the compute-profile filter, the filler filter, and the status sets.
Only the three external boundaries are mocked (Code Engine submit, COS
arguments upload, and the runner used to cancel a fleet).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry

from core.config_key import ConfigKey
from core.models import ComputeProfile, Config, FunctionSize, Job, JobEvent, Program
from core.model_managers.job_events import JobEventContext
from core.services.runners import RunnerError
from scheduler.main import Main
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.balance_filler_jobs import BalanceFillerJobs, _Throttle
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.balance_filler_jobs"
_PROFILE = "160x1792x8h100"
_AUTHOR = "FillerId"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    return BalanceFillerJobs(kill_signal=kill_signal, metrics=MagicMock())


@pytest.fixture
def filler_program():
    """A Fleets program with a Code Engine project and a default size on the scarce profile."""
    Config.add_defaults()
    program = TestUtils.create_program(
        program_title="filler-function",
        author="filler_program_owner",
        runner=Program.FLEETS,
        code_engine_project=TestUtils.get_or_create_ce_project(
            project_name="ce-filler", project_id="ce-id", cos_bucket_user_data_name="filler-bucket"
        ),
    )
    profile = ComputeProfile.objects.create(compute_profile_id=_PROFILE, cpu="160", memory="1792", gpu="8h100")
    program.default_size = FunctionSize.objects.create(function=program, function_size="l", compute_profile=profile)
    program.save()
    TestUtils.get_user_and_username(_AUTHOR)
    Config.set(ConfigKey.FILLER_ENABLED, "true")
    Config.set(ConfigKey.FILLER_PROGRAM_ID, str(program.id))
    Config.set(ConfigKey.FILLER_SLOTS, "4")
    return program


def _run(task, times=1):
    """Run `times` scheduler iterations with the three external boundaries mocked out.

    The task creates one filler job per iteration, so a test that wants a profile
    filled asks for as many iterations as there are slots. The mocks stay in place
    across all of them, so the returned call counts are the totals.
    """
    with (
        patch(f"{_MOD}.execute_fleets_job", side_effect=_fake_submit) as submit,
        patch(f"{_MOD}.get_arguments_storage") as arguments,
        patch(f"{_MOD}.get_runner") as runner,
    ):
        for _ in range(times):
            task.run()
    return submit, arguments, runner


def _fake_submit(job, ctx, context=None):  # pylint: disable=unused-argument
    """Stand in for execute_fleets_job: mark the job PENDING as a real submit would."""
    job.update_fields({"status": Job.PENDING})
    return job


class TestThrottle:
    """The per-key log throttling and retry backoff the balancer runs on."""

    def test_a_repeated_message_drops_to_debug(self, caplog):
        """The loop runs once a second, so the same line must not be reported twice."""
        throttle = _Throttle()

        with caplog.at_level(logging.DEBUG, logger="scheduler.BalanceFillerJobs"):
            throttle.log("status", logging.INFO, "profile=%s", _PROFILE)
            throttle.log("status", logging.INFO, "profile=%s", _PROFILE)

        assert [record.levelno for record in caplog.records] == [logging.INFO, logging.DEBUG]

    def test_clear_lets_a_recurrence_be_reported_again(self, caplog):
        """Throttling silences repeats, not recurrences."""
        throttle = _Throttle()

        with caplog.at_level(logging.DEBUG, logger="scheduler.BalanceFillerJobs"):
            throttle.log("status", logging.INFO, "profile=%s", _PROFILE)
            throttle.clear("status")
            throttle.log("status", logging.INFO, "profile=%s", _PROFILE)

        assert [record.levelno for record in caplog.records] == [logging.INFO, logging.INFO]

    def test_a_retry_delay_counts_down_and_runs_out(self):
        """The countdown advances per call, so it only moves on loops that ask for it."""
        throttle = _Throttle()
        throttle.set_retry("create", 2)

        assert [throttle.wait_before_retry("create") for _ in range(3)] == [True, True, False]

    def test_clear_does_not_cancel_a_pending_retry(self):
        """The two halves are independent: reportable again is not the same as due again."""
        throttle = _Throttle()
        throttle.set_retry("create", 1)

        throttle.clear("create")

        assert throttle.wait_before_retry("create") is True

    def test_forget_stale_drops_only_the_keys_that_are_gone(self):
        """State keyed by job has to be pruned as filler jobs come and go."""
        throttle = _Throttle()
        for key in ("stop:gone", "stop:live", "create"):
            throttle.set_retry(key, 5)

        throttle.forget_stale("stop:", {"stop:live"})

        assert throttle.wait_before_retry("stop:gone") is False
        assert throttle.wait_before_retry("stop:live") is True
        assert throttle.wait_before_retry("create") is True


def test_creates_filler_jobs_up_to_the_configured_slots(filler_program):
    """With no real jobs and four slots, four iterations create four filler jobs."""
    task = _make_task()

    submit, arguments, _ = _run(task, times=4)

    fillers = Job.objects.filter(filler=True)
    assert fillers.count() == 4
    assert submit.call_count == 4
    assert arguments.call_count == 4
    assert {job.compute_profile for job in fillers} == {_PROFILE}
    assert {job.runner for job in fillers} == {Program.FLEETS}
    assert {job.author.username for job in fillers} == {_AUTHOR}
    assert submit.call_args.kwargs["context"] is JobEventContext.FILLER_SUBMIT


def test_real_running_jobs_reduce_the_number_of_filler_jobs(filler_program):
    """Two real jobs on the profile leave room for two filler jobs."""
    for index in range(2):
        TestUtils.create_job(
            author=f"real_user_{index}",
            program=filler_program,
            status=Job.RUNNING,
            runner=Program.FLEETS,
            compute_profile=_PROFILE,
            compute_profile_fk=filler_program.default_size.compute_profile,
        )
    task = _make_task()

    _run(task, times=4)

    assert Job.objects.filter(filler=True).count() == 2


def test_a_prefixed_profile_row_still_counts_real_jobs(filler_program):
    """Occupancy is counted on the ComputeProfile row, not on the profile string.

    ComputeProfile primary keys are free text, so a row can carry the prefixed form.
    The t-shirt size paths store that key verbatim on the job while this task
    normalizes it, so a string comparison would count zero and over-provision the
    node. This is the case the foreign-key count exists for.
    """
    prefixed = ComputeProfile.objects.create(
        compute_profile_id="gx3d-160x1792x8h100", cpu="160", memory="1792", gpu="8h100"
    )
    filler_program.default_size.compute_profile = prefixed
    filler_program.default_size.save()
    TestUtils.create_job(
        author="real_user",
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=prefixed.compute_profile_id,
        compute_profile_fk=prefixed,
    )
    task = _make_task()

    _run(task, times=4)

    assert Job.objects.filter(filler=True).count() == 3


def test_real_jobs_on_another_profile_do_not_count(filler_program):
    """A running job on a different compute profile leaves all four slots to fill."""
    other = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
    TestUtils.create_job(
        author="real_user",
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=other.compute_profile_id,
        compute_profile_fk=other,
    )
    task = _make_task()

    _run(task, times=4)

    assert Job.objects.filter(filler=True).count() == 4


def test_stops_the_oldest_filler_jobs_when_there_are_too_many(filler_program):
    """Lowering the slots stops the excess, oldest first, and cancels the fleet."""
    jobs = [
        TestUtils.create_job(
            author=_AUTHOR,
            program=filler_program,
            status=Job.RUNNING,
            runner=Program.FLEETS,
            compute_profile=_PROFILE,
            compute_profile_fk=filler_program.default_size.compute_profile,
            filler=True,
            fleet_id=f"fleet-{index}",
        )
        for index in range(3)
    ]
    Config.set(ConfigKey.FILLER_SLOTS, "1")
    task = _make_task()

    _, _, runner = _run(task)

    jobs[0].refresh_from_db()
    jobs[1].refresh_from_db()
    jobs[2].refresh_from_db()
    assert jobs[0].status == Job.STOPPED
    assert jobs[1].status == Job.STOPPED
    assert jobs[2].status == Job.RUNNING
    assert runner.return_value.stop.call_count == 2
    assert JobEvent.objects.filter(job=jobs[0], context=JobEventContext.FILLER_STOP).exists()


def test_does_nothing_when_the_count_already_matches(filler_program):
    """Four filler jobs and four slots means no submit and no stop."""
    for index in range(4):
        TestUtils.create_job(
            author=_AUTHOR,
            program=filler_program,
            status=Job.RUNNING,
            runner=Program.FLEETS,
            compute_profile=_PROFILE,
            compute_profile_fk=filler_program.default_size.compute_profile,
            filler=True,
            fleet_id=f"fleet-{index}",
        )
    task = _make_task()

    submit, _, runner = _run(task)

    assert submit.call_count == 0
    assert runner.return_value.stop.call_count == 0
    assert Job.objects.filter(filler=True, status=Job.RUNNING).count() == 4


def test_zero_slots_stops_every_filler_job(filler_program):
    """FILLER_SLOTS=0 is the same as switching the feature off: clean everything up."""
    TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
        fleet_id="fleet-0",
    )
    Config.set(ConfigKey.FILLER_SLOTS, "0")
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True, status=Job.STOPPED).count() == 1


@pytest.mark.parametrize(
    "config_key,value",
    [
        (ConfigKey.FILLER_ENABLED, "false"),
        (ConfigKey.FILLER_PROGRAM_ID, ""),
        (ConfigKey.FILLER_PROGRAM_ID, "not-a-uuid"),
        (ConfigKey.MAINTENANCE, "true"),
    ],
)
def test_deactivated_stops_every_filler_job(filler_program, config_key, value):
    """Every deactivated condition creates nothing and cleans up what is running."""
    TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
        fleet_id="fleet-0",
    )
    Config.set(config_key, value)
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True, status=Job.STOPPED).count() == 1


def test_a_program_without_a_default_size_deactivates_the_feature(filler_program):
    """No default_size means no profile to derive, so the feature is off."""
    filler_program.default_size = None
    filler_program.save()
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True).count() == 0


def test_a_ray_program_deactivates_the_feature(filler_program):
    """A filler program on the Ray runner would write its arguments to the wrong storage."""
    filler_program.runner = Program.RAY
    filler_program.save()
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True).count() == 0


def test_a_missing_filler_author_deactivates_the_feature(filler_program, settings):
    """Without the configured author there is nobody to own the filler jobs."""
    settings.FILLER_AUTHOR_USERNAME = "nobody-here"
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True).count() == 0


def test_an_inactive_code_engine_project_deactivates_the_feature(filler_program):
    """FleetsRunner refuses an inactive project, so submitting would only make FAILED jobs."""
    project = filler_program.code_engine_project
    project.active = False
    project.save()
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True).count() == 0


def test_a_disabled_filler_program_deactivates_the_feature(filler_program):
    """Disabling the function in the admin is the intuitive way to switch this off."""
    filler_program.disabled = True
    filler_program.save()
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0
    assert Job.objects.filter(filler=True).count() == 0


def test_a_filler_job_that_was_never_submitted_is_discarded(filler_program):
    """A filler job stuck in QUEUED with no fleet would otherwise hold a slot forever."""
    stuck = TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.QUEUED,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
    )
    task = _make_task()

    _run(task)

    stuck.refresh_from_db()
    assert stuck.status == Job.STOPPED
    assert JobEvent.objects.filter(job=stuck, context=JobEventContext.FILLER_STOP).exists()


def test_filler_jobs_on_another_profile_are_always_stopped(filler_program):
    """Re-pointing the profile stops the filler jobs left on the old one.

    The old row's id normalizes to the SAME string as the protected one, which is
    what makes this test worth having: classifying on the string would leave these
    jobs alone forever, holding a profile the balancer no longer protects. Only the
    ComputeProfile row tells them apart.
    """
    old_row = ComputeProfile.objects.create(
        compute_profile_id="gx3d-160x1792x8h100", cpu="160", memory="1792", gpu="8h100"
    )
    stale = TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=old_row,
        filler=True,
        fleet_id="fleet-stale",
    )
    task = _make_task()

    submit, _, _ = _run(task, times=4)

    stale.refresh_from_db()
    assert stale.status == Job.STOPPED
    # The stale one never counted towards the target, so all four slots are filled.
    assert submit.call_count == 4


def test_filler_jobs_of_another_program_are_always_stopped(filler_program):
    """Re-pointing the feature at another program stops the filler jobs of the old one.

    They sit on the right compute profile, so the profile check alone leaves them
    running: the operator changed which code should hold that capacity, and these
    jobs are running the code that was replaced.
    """
    old_program = TestUtils.create_program(
        program_title="old-filler-function",
        author="filler_program_owner",
        runner=Program.FLEETS,
    )
    stale = TestUtils.create_job(
        author=_AUTHOR,
        program=old_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
        fleet_id="fleet-old-program",
    )
    task = _make_task()

    submit, _, _ = _run(task, times=4)

    stale.refresh_from_db()
    assert stale.status == Job.STOPPED
    # It never counted towards the target either, so all four slots are filled.
    assert submit.call_count == 4


def test_one_filler_job_is_submitted_per_loop(filler_program):
    """The shortfall is filled one job per iteration, not all at once."""
    Config.set(ConfigKey.FILLER_SLOTS, "10")
    task = _make_task()

    submit, _, _ = _run(task, times=3)

    assert submit.call_count == 3
    assert Job.objects.filter(filler=True).count() == 3


def test_the_churn_breaker_stops_creating_when_filler_jobs_die_on_their_own(filler_program):
    """Five filler jobs that ended by themselves recently block further creation."""
    for index in range(5):
        TestUtils.create_job(
            author=_AUTHOR,
            program=filler_program,
            status=Job.FAILED,
            runner=Program.FLEETS,
            compute_profile=_PROFILE,
            compute_profile_fk=filler_program.default_size.compute_profile,
            filler=True,
            fleet_id=f"dead-{index}",
        )
    task = _make_task()

    submit, _, _ = _run(task)

    assert submit.call_count == 0


def test_stopped_filler_jobs_do_not_trip_the_churn_breaker(filler_program):
    """Filler jobs the balancer stopped are the feature working, not churn."""
    for index in range(6):
        TestUtils.create_job(
            author=_AUTHOR,
            program=filler_program,
            status=Job.STOPPED,
            runner=Program.FLEETS,
            compute_profile=_PROFILE,
            compute_profile_fk=filler_program.default_size.compute_profile,
            filler=True,
            fleet_id=f"stopped-{index}",
        )
    task = _make_task()

    submit, _, _ = _run(task, times=4)

    assert submit.call_count == 4


def test_a_fleet_that_cannot_be_cancelled_keeps_the_job_active(filler_program):
    """A failed cancel leaves the job active so the next loop retries it."""
    job = TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
        fleet_id="fleet-stuck",
    )
    Config.set(ConfigKey.FILLER_SLOTS, "0")
    task = _make_task()

    with (
        patch(f"{_MOD}.execute_fleets_job"),
        patch(f"{_MOD}.get_arguments_storage"),
        patch(f"{_MOD}.get_runner") as runner,
    ):
        runner.return_value.stop.side_effect = RunnerError("Code Engine said no")
        task.run()

    job.refresh_from_db()
    assert job.status == Job.RUNNING


def test_a_failed_cancel_is_not_retried_every_loop(filler_program):
    """Retrying a doomed cancel once a second would be 86,400 Code Engine calls a day."""
    TestUtils.create_job(
        author=_AUTHOR,
        program=filler_program,
        status=Job.RUNNING,
        runner=Program.FLEETS,
        compute_profile=_PROFILE,
        compute_profile_fk=filler_program.default_size.compute_profile,
        filler=True,
        fleet_id="fleet-stuck",
    )
    Config.set(ConfigKey.FILLER_SLOTS, "0")
    task = _make_task()

    with (
        patch(f"{_MOD}.execute_fleets_job"),
        patch(f"{_MOD}.get_arguments_storage"),
        patch(f"{_MOD}.get_runner") as runner,
    ):
        runner.return_value.stop.side_effect = RunnerError("Code Engine said no")
        task.run()
        task.run()
        task.run()

    assert runner.return_value.stop.call_count == 1


def test_a_condition_that_comes_back_is_logged_again(filler_program, caplog):
    """Throttling silences repeats, not recurrences."""
    Config.set(ConfigKey.FILLER_ENABLED, "false")
    task = _make_task()

    with caplog.at_level(logging.INFO, logger="scheduler.BalanceFillerJobs"):
        _run(task)
        Config.set(ConfigKey.FILLER_ENABLED, "true")
        _run(task)
        Config.set(ConfigKey.FILLER_ENABLED, "false")
        _run(task)

    deactivated = [r for r in caplog.records if "deactivated" in r.message and r.levelno == logging.INFO]
    assert len(deactivated) == 2


def test_a_failed_creation_is_not_retried_every_loop(filler_program):
    """A COS problem must not mean a submit attempt every second."""
    task = _make_task()

    with (
        patch(f"{_MOD}.execute_fleets_job"),
        patch(f"{_MOD}.get_arguments_storage", side_effect=ValueError("no bucket")) as arguments,
        patch(f"{_MOD}.get_runner"),
    ):
        task.run()
        task.run()
        task.run()

    assert arguments.call_count == 1
    assert Job.objects.filter(filler=True).count() == 0


def test_a_creation_that_fails_before_the_submit_discards_the_row(filler_program):
    """A row that was saved but never submitted is discarded in the same loop."""
    task = _make_task()

    with (
        patch(f"{_MOD}.execute_fleets_job", side_effect=ValueError("no runner")),
        patch(f"{_MOD}.get_arguments_storage"),
        patch(f"{_MOD}.get_runner"),
    ):
        task.run()

    job = Job.objects.get(filler=True)
    assert job.status == Job.STOPPED
    assert JobEvent.objects.filter(job=job, context=JobEventContext.FILLER_STOP).exists()


def test_the_balancer_runs_after_the_fleets_status_update(settings):
    """The balancer must see the freshest real-job count, so its position matters.

    UpdateFleetsJobsStatuses must run before BalanceFillerJobs (so real jobs that
    finished this loop are already reflected), and FreeResources must run after it
    (Ray-only cleanup has nothing to do with when the balancer runs, but the plan
    fixes this as the position).
    """
    # A different port from tests/scheduler/test_main.py, which also constructs a
    # real Main and binds SITE_HOST, so the two cannot collide.
    settings.SITE_HOST = "http://127.0.0.1:8201"
    scheduler_main = Main(metrics=SchedulerMetrics(CollectorRegistry()))
    try:
        names = [type(task).__name__ for task in scheduler_main.tasks]
        assert names.index("UpdateFleetsJobsStatuses") < names.index("BalanceFillerJobs") < names.index("FreeResources")
    finally:
        scheduler_main.stop_http_server()
