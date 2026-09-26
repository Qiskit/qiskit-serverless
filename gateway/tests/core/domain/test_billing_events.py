"""Unit tests for the billing event builders. Pure functions: everything constructed in memory,
no database access, no pytest.mark.django_db."""

import logging
from datetime import datetime, timedelta, timezone

from core.domain.billing_events import build_billing_event_message, build_license_fee_message
from core.domain.business_models import BusinessModel
from core.models import ComputeProfile, FunctionSize, Job, JobEvent, Program, Provider


def _job(**overrides) -> Job:
    defaults = dict(
        instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::",
        compute_profile="16x128",
        business_model=BusinessModel.LICENSED,
    )
    defaults.update(overrides)
    return Job(**defaults)


def _event(created=None) -> JobEvent:
    return JobEvent(created=created or datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc))


class TestBuildBillingEventMessage:
    def test_reports_zero_seconds_when_the_job_never_ran(self):
        job = _job()
        event = _event()

        message = build_billing_event_message(job, event, running_started_at=None)

        assert message["data"]["metric_value"] == 0
        assert message["data"]["job_started_at"] is None
        assert message["data"]["job_completed"] is True

    def test_computes_seconds_from_running_started_at_to_the_events_own_timestamp(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        event = _event(created=running_started_at + timedelta(seconds=90))

        message = build_billing_event_message(job, event, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 90

    def test_rounds_a_partial_second_up(self):
        job = _job()
        running_started_at = datetime(2026, 9, 25, 11, 59, 0, tzinfo=timezone.utc)
        event = _event(created=running_started_at + timedelta(seconds=90, milliseconds=200))

        message = build_billing_event_message(job, event, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 91

    def test_never_negative_when_as_of_precedes_running_started_at(self):
        """Clock skew between processes could otherwise put as_of before running_started_at."""
        job = _job()
        running_started_at = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
        event = _event(created=running_started_at - timedelta(seconds=5))

        message = build_billing_event_message(job, event, running_started_at=running_started_at)

        assert message["data"]["metric_value"] == 0

    def test_envelope_identifies_the_job_and_omits_type(self):
        job = _job()
        event = _event()

        message = build_billing_event_message(job, event, running_started_at=None)

        assert message["subject"] == str(job.id)
        assert message["data"]["resource_id"] == str(job.id)
        assert message["data"]["instance_crn"] == job.instance_crn
        assert "type" not in message  # added later by KafkaOutboxSender, not here

    def test_metric_type_includes_compute_profile(self):
        job = _job(compute_profile="16x128")
        message = build_billing_event_message(job, _event(), running_started_at=None)

        assert message["data"]["metric_type"] == "classical_16x128"


class TestBuildLicenseFeeMessage:
    def test_none_when_the_function_has_no_provider(self):
        job = _job(program=Program(title="my-fn", provider=None))

        message = build_license_fee_message(job, _event(), running_started_at=None)

        assert message is None

    def test_none_when_the_program_is_missing(self):
        job = _job(program=None)

        message = build_license_fee_message(job, _event(), running_started_at=None)

        assert message is None

    def test_none_and_logs_an_error_when_function_size_is_missing_despite_a_provider(self, caplog):
        provider = Provider(name="ibm-dev")
        job = _job(program=Program(title="my-fn", provider=provider), function_size=None)

        with caplog.at_level(logging.ERROR):
            message = build_license_fee_message(job, _event(), running_started_at=None)

        assert message is None
        assert "waiving the fee" in caplog.text

    def test_built_when_provider_and_function_size_are_present(self):
        provider = Provider(name="ibm-dev")
        program = Program(title="my-fn", provider=provider)
        function_size = FunctionSize(function_size="m", compute_profile=ComputeProfile(compute_profile_id="16x128"))
        job = _job(program=program, function_size=function_size)
        running_started_at = datetime(2026, 9, 25, 11, 0, 0, tzinfo=timezone.utc)

        message = build_license_fee_message(job, _event(), running_started_at=running_started_at)

        assert message["data"]["metric_type"] == "license_ibm-dev_my-fn_m"
        assert message["data"]["metric_value"] == 1
        assert message["data"]["business_model"] == "licensed"
        assert message["data"]["job_started_at"] == running_started_at.isoformat()
        assert message["data"]["job_started"] is True
        assert message["data"]["job_completed"] is True
