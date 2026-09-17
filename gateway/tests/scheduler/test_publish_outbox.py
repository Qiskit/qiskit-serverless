"""Unit tests for PublishOutbox."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scheduler.tasks.publish_outbox import PublishOutbox

_MOD = "scheduler.tasks.publish_outbox"


def _make_task():
    kill_signal = MagicMock()
    kill_signal.received = False
    task = PublishOutbox.__new__(PublishOutbox)
    task.kill_signal = kill_signal
    task.metrics = MagicMock()
    task._event_streams_client = MagicMock()
    task._breaker = MagicMock()
    task._breaker.is_open = False
    return task


def _make_row(
    job_id="job-1",
    license_fee_required=True,
    license_fee_sent_at=None,
    billing_sent_at=None,
    status_changed_at=None,
):
    row = MagicMock()
    row.job_id = job_id
    row.job = MagicMock()
    row.license_fee_required = license_fee_required
    row.license_fee_sent_at = license_fee_sent_at
    row.billing_sent_at = billing_sent_at
    row.status_changed_at = status_changed_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.save = MagicMock()
    return row


class TestDisabledFlag:
    def test_returns_immediately_when_disabled(self):
        task = _make_task()

        with patch(f"{_MOD}.Config") as mock_config:
            mock_config.get_bool.return_value = False
            with patch(f"{_MOD}.JobOutbox") as mock_job_outbox:
                task.run()

        mock_job_outbox.objects.pending_kafka_outbox.assert_not_called()


class TestHappyPath:
    def test_sends_license_fee_and_billing_event_and_marks_both_sent(self):
        task = _make_task()
        row = _make_row(license_fee_required=True)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.side_effect = lambda key, default=None: {"batch_size": 20, "budget_ms": 500}.get(
                key.value.rsplit(".", 1)[-1], default
            )
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True
            now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_license_fee.assert_called_once_with(row.job)
        task.event_streams_client.emit_job_completed.assert_called_once_with(row.job, row.status_changed_at)
        assert row.license_fee_sent_at == now
        assert row.billing_sent_at == now
        row.save.assert_called_once()

    def test_skips_license_fee_when_not_required(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True

            task.run()

        task.event_streams_client.emit_license_fee.assert_not_called()
        task.event_streams_client.emit_job_completed.assert_called_once()

    def test_skips_billing_event_when_already_sent(self):
        task = _make_task()
        already_sent = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        row = _make_row(license_fee_required=True, billing_sent_at=already_sent)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True

            task.run()

        task.event_streams_client.emit_job_completed.assert_not_called()
        task.event_streams_client.emit_license_fee.assert_called_once()
        assert row.billing_sent_at == already_sent


class TestFailureHandling:
    def test_network_failure_does_not_mark_sent_and_records_failure_on_the_breaker(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)
        task.event_streams_client.emit_job_completed.side_effect = RuntimeError("kafka down")

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]

            task.run()

        assert row.billing_sent_at is None
        task._breaker.record_failure.assert_called_once()
        row.save.assert_not_called()

    def test_license_fee_payload_failure_is_recorded_without_blocking_the_billing_event(self):
        task = _make_task()
        row = _make_row(license_fee_required=True)
        task.event_streams_client.emit_license_fee.side_effect = AttributeError("'NoneType' object has no 'provider'")

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = False
            mock_timezone.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

            task.run()

        assert row.license_fee_sent_at is None
        task.metrics.increment_outbox_license_fee_irrecoverable.assert_called_once()
        task.event_streams_client.emit_job_completed.assert_called_once()
        assert row.billing_sent_at is not None
        task._breaker.record_failure.assert_not_called()

    def test_skips_the_breaker_when_open(self):
        task = _make_task()
        task._breaker.is_open = True
        row = _make_row()

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]

            task.run()

        task.event_streams_client.emit_job_completed.assert_not_called()
        task.event_streams_client.emit_license_fee.assert_not_called()
        task.metrics.set_outbox_breaker_open.assert_called_with(True)


class TestBudgetAndKillSignal:
    def test_stops_once_the_time_budget_is_spent(self):
        task = _make_task()
        rows = [_make_row(job_id=f"job-{i}", license_fee_required=False) for i in range(3)]

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
            patch(f"{_MOD}.time.monotonic", side_effect=[0.0, 0.0, 0.6, 0.6]),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.side_effect = lambda key, default=None: {"budget_ms": 500, "batch_size": 20}.get(
                key.value.rsplit(".", 1)[-1], default
            )
            mock_job_outbox.objects.pending_kafka_outbox.return_value = rows
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 1

    def test_stops_between_rows_when_kill_signal_received(self):
        task = _make_task()
        rows = [_make_row(job_id=f"job-{i}", license_fee_required=False) for i in range(2)]

        def receive_after_first(*_args, **_kwargs):
            task.kill_signal.received = True
            return MagicMock()

        task.event_streams_client.emit_job_completed.side_effect = receive_after_first

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = rows
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 1


class TestDeletion:
    def test_deletes_the_row_once_ready(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = True

            task.run()

        row.delete.assert_called_once()

    def test_keeps_the_row_when_not_ready(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            mock_job_outbox.objects.pending_kafka_outbox.return_value = [row]
            mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.exists.return_value = False

            task.run()

        row.delete.assert_not_called()
