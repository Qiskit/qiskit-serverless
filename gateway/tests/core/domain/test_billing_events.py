"""Unit tests for BillingEvents' message builders. Pure functions: everything constructed in
memory, no database access, no pytest.mark.django_db."""

from datetime import datetime, timedelta, timezone

from core.domain.billing_events import BillingEvents
from core.domain.business_models import BusinessModel
from core.models import ComputeProfile, FunctionSize, Job, Program, Provider


def _job(**overrides) -> Job:
    defaults = dict(
        instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
        compute_profile="16x128",
        business_model=BusinessModel.LICENSED,
        filler=False,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestBuildJobUsageEvent:
    def test_job_last_progress_time_none_forces_zero_usage_and_marks_job_started(self):
        job = _job()
        job_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_job_usage(job, job_started_at, job_last_progress_time=None)

        assert message["data"] == {
            "metric_type": "classical_16x128",
            "metric_value": 0,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_started_at": job_started_at.isoformat(),
            "job_completed": False,
        }

    def test_computes_seconds_from_job_started_at_to_job_last_progress_time(self):
        job = _job()
        job_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        job_last_progress_time = job_started_at + timedelta(seconds=5)

        message = BillingEvents.build_job_usage(job, job_started_at, job_last_progress_time)

        assert message["data"] == {
            "metric_type": "classical_16x128",
            "metric_value": 5,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": False,
            "job_started_at": job_started_at.isoformat(),
            "job_completed": False,
        }

    def test_never_negative_when_job_last_progress_time_precedes_job_started_at(self):
        """Clock skew between processes could otherwise put job_last_progress_time before job_started_at."""
        job = _job()
        job_started_at = datetime(2026, 9, 25, 12, 0, 5, tzinfo=timezone.utc)
        job_last_progress_time = job_started_at - timedelta(seconds=5)

        message = BillingEvents.build_job_usage(job, job_started_at, job_last_progress_time)

        assert message["data"]["metric_value"] == 0

    def test_envelope_omits_type(self):
        job = _job()
        job_started_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_job_usage(job, job_started_at, datetime.now(timezone.utc))

        assert "type" not in message  # added later by the sender, not here
        assert message["subject"] == str(job.id)
        assert message["specversion"] == "1.0"
        assert message["source"] == "qiskit-serverless/scheduler/fleets"
        assert message["datacontenttype"] == "application/json"


class TestBuildJobCompletedEvent:
    def test_reports_zero_seconds_when_the_job_never_ran(self):
        job = _job()
        job_finished_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_job_completed_event(job, None, job_finished_at)

        assert message["data"]["metric_value"] == 0
        assert message["data"]["job_started_at"] is None
        assert message["data"]["job_completed"] is True

    def test_computes_seconds_from_job_started_at_to_job_finished_at(self):
        job = _job()
        job_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        job_finished_at = job_started_at + timedelta(seconds=90)

        message = BillingEvents.build_job_completed_event(job, job_started_at, job_finished_at)

        assert message["data"]["metric_value"] == 90

    def test_rounds_a_partial_second_up(self):
        job = _job()
        job_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        job_finished_at = job_started_at + timedelta(seconds=90, milliseconds=200)

        message = BillingEvents.build_job_completed_event(job, job_started_at, job_finished_at)

        assert message["data"]["metric_value"] == 91

    def test_never_negative_when_job_finished_at_precedes_job_started_at(self):
        """Clock skew between processes could otherwise put job_finished_at before job_started_at."""
        job = _job()
        job_started_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
        job_finished_at = job_started_at - timedelta(seconds=5)

        message = BillingEvents.build_job_completed_event(job, job_started_at, job_finished_at)

        assert message["data"]["metric_value"] == 0

    def test_envelope_identifies_the_job_and_omits_type(self):
        job = _job()

        message = BillingEvents.build_job_completed_event(job, None, datetime.now(timezone.utc))

        assert message["subject"] == str(job.id)
        assert message["data"]["resource_id"] == str(job.id)
        assert message["data"]["instance_crn"] == job.instance_crn
        assert "type" not in message  # added later by the sender, not here

    def test_metric_type_includes_compute_profile(self):
        job = _job(compute_profile="16x128")

        message = BillingEvents.build_job_completed_event(job, None, datetime.now(timezone.utc))

        assert message["data"]["metric_type"] == "classical_16x128"


class TestBuildLicenseFee:
    def test_built_when_provider_and_function_size_are_present(self):
        provider = Provider(name="ibm-dev")
        program = Program(title="my-fn", provider=provider)
        function_size = FunctionSize(function_size="m", compute_profile=ComputeProfile(compute_profile_id="16x128"))
        job = _job(program=program, function_size=function_size)
        running_started_at = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_license_fee(job, running_started_at)

        assert message["data"]["metric_type"] == "license_ibm-dev_my-fn_m"
        assert message["data"]["metric_value"] == 1
        assert message["data"]["business_model"] == "licensed"
        assert message["data"]["job_started_at"] == running_started_at.isoformat()
        assert message["data"]["job_started"] is True
        assert message["data"]["job_completed"] is True

    def test_running_started_at_none_for_a_job_that_succeeded_without_ever_running(self):
        """The one case where running_started_at is None: a direct PENDING -> SUCCEEDED
        transition, never through RUNNING."""
        provider = Provider(name="ibm-dev")
        program = Program(title="my-fn", provider=provider)
        function_size = FunctionSize(function_size="m", compute_profile=ComputeProfile(compute_profile_id="16x128"))
        job = _job(program=program, function_size=function_size)

        message = BillingEvents.build_license_fee(job, job_started_at=None)

        assert message["data"]["job_started_at"] is None
        assert message["data"]["metric_value"] == 1
