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


class TestBuildJobInProgress:
    def test_job_started_forces_zero_usage_regardless_of_running_started_at(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        as_of = running_started_at + timedelta(seconds=5)

        message = BillingEvents.build_job_in_progress(
            job, as_of, running_started_at=running_started_at, job_started=True
        )

        assert message["data"] == {
            "metric_type": "classical_16x128",
            "metric_value": 0,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": True,
            "job_started_at": running_started_at.isoformat(),
            "job_completed": False,
        }

    def test_computes_seconds_from_running_started_at_to_as_of(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        as_of = running_started_at + timedelta(seconds=5)

        message = BillingEvents.build_job_in_progress(job, as_of, running_started_at=running_started_at)

        assert message["data"] == {
            "metric_type": "classical_16x128",
            "metric_value": 5,
            "instance_crn": job.instance_crn,
            "resource_id": str(job.id),
            "job_started": False,
            "job_started_at": running_started_at.isoformat(),
            "job_completed": False,
        }

    def test_reports_zero_usage_when_never_running(self):
        job = _job()

        message = BillingEvents.build_job_in_progress(
            job, datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc), running_started_at=None
        )

        assert message["data"]["metric_value"] == 0
        assert message["data"]["job_started_at"] is None

    def test_never_negative_when_as_of_precedes_running_started_at(self):
        """Clock skew between processes could otherwise put as_of before running_started_at."""
        job = _job()
        running_started_at = datetime(2026, 9, 25, 12, 0, 5, tzinfo=timezone.utc)
        as_of = running_started_at - timedelta(seconds=5)

        message = BillingEvents.build_job_in_progress(job, as_of, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 0

    def test_envelope_omits_type(self):
        job = _job()

        message = BillingEvents.build_job_in_progress(job, datetime.now(timezone.utc), running_started_at=None)

        assert "type" not in message  # added later by the sender, not here
        assert message["subject"] == str(job.id)
        assert message["specversion"] == "1.0"
        assert message["source"] == "qiskit-serverless/scheduler/fleets"
        assert message["datacontenttype"] == "application/json"


class TestBuildBillingEvent:
    def test_reports_zero_seconds_when_the_job_never_ran(self):
        job = _job()
        as_of = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_billing_event(job, as_of, running_started_at=None)

        assert message["data"]["metric_value"] == 0
        assert message["data"]["job_started_at"] is None
        assert message["data"]["job_completed"] is True

    def test_computes_seconds_from_running_started_at_to_as_of(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        as_of = running_started_at + timedelta(seconds=90)

        message = BillingEvents.build_billing_event(job, as_of, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 90

    def test_rounds_a_partial_second_up(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        as_of = running_started_at + timedelta(seconds=90, milliseconds=200)

        message = BillingEvents.build_billing_event(job, as_of, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 91

    def test_never_negative_when_as_of_precedes_running_started_at(self):
        """Clock skew between processes could otherwise put as_of before running_started_at."""
        job = _job()
        running_started_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
        as_of = running_started_at - timedelta(seconds=5)

        message = BillingEvents.build_billing_event(job, as_of, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 0

    def test_envelope_identifies_the_job_and_omits_type(self):
        job = _job()

        message = BillingEvents.build_billing_event(job, datetime.now(timezone.utc), running_started_at=None)

        assert message["subject"] == str(job.id)
        assert message["data"]["resource_id"] == str(job.id)
        assert message["data"]["instance_crn"] == job.instance_crn
        assert "type" not in message  # added later by the sender, not here

    def test_metric_type_includes_compute_profile(self):
        job = _job(compute_profile="16x128")

        message = BillingEvents.build_billing_event(job, datetime.now(timezone.utc), running_started_at=None)

        assert message["data"]["metric_type"] == "classical_16x128"


class TestBuildLicenseFee:
    def test_built_when_provider_and_function_size_are_present(self):
        provider = Provider(name="ibm-dev")
        program = Program(title="my-fn", provider=provider)
        function_size = FunctionSize(function_size="m", compute_profile=ComputeProfile(compute_profile_id="16x128"))
        job = _job(program=program, function_size=function_size)
        running_started_at = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone.utc)

        message = BillingEvents.build_license_fee(
            job, datetime.now(timezone.utc), running_started_at=running_started_at
        )

        assert message["data"]["metric_type"] == "license_ibm-dev_my-fn_m"
        assert message["data"]["metric_value"] == 1
        assert message["data"]["business_model"] == "licensed"
        assert message["data"]["job_started_at"] == running_started_at.isoformat()
        assert message["data"]["job_started"] is True
        assert message["data"]["job_completed"] is True
