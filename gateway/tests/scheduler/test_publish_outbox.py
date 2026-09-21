"""Unit tests for PublishOutbox."""

from datetime import datetime, timezone
from itertools import chain, repeat
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
    row.pk = job_id
    row.job_id = job_id
    row.job = MagicMock()
    row.license_fee_required = license_fee_required
    row.license_fee_sent_at = license_fee_sent_at
    row.billing_sent_at = billing_sent_at
    row.status_changed_at = status_changed_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    row.save = MagicMock()
    return row


def _configure_pending(mock_job_outbox, license_fee_pks=None, billing_event_pks=None, rows=None, batches=None):
    """Wire the pk-set lookups (scoped to a batch, via filter(pk__in=...)) and the sequence
    of batches PublishOutbox.run() fetches, one per outer-loop iteration.

    Pass `rows` for a single batch, or `batches` (a list of row-lists) to exercise more than
    one iteration of the outer loop. Either way, the sequence is padded with empty batches
    so the loop always has a batch to end on, however many times it asks.
    """
    mock_job_outbox.objects.pending_license_fee.return_value.filter.return_value.values_list.return_value = (
        license_fee_pks or []
    )
    mock_job_outbox.objects.pending_billing_event.return_value.filter.return_value.values_list.return_value = (
        billing_event_pks or []
    )
    combined = mock_job_outbox.objects.pending_license_fee.return_value.__or__.return_value
    combined.order_by.return_value.__getitem__.side_effect = chain(
        batches if batches is not None else [rows or []], repeat([])
    )


class TestDisabledFlag:
    def test_returns_immediately_when_disabled(self):
        task = _make_task()

        with patch(f"{_MOD}.Config") as mock_config:
            mock_config.get_bool.return_value = False
            with patch(f"{_MOD}.JobOutbox") as mock_job_outbox:
                task.run()

        mock_job_outbox.objects.pending_license_fee.assert_not_called()
        mock_job_outbox.objects.pending_billing_event.assert_not_called()


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
            mock_config.get_int.return_value = 500
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], billing_event_pks=[row.pk], rows=[row])
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
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])

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
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])

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
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])

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
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], billing_event_pks=[row.pk], rows=[row])
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

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20

            task.run()

        task.event_streams_client.emit_job_completed.assert_not_called()
        task.event_streams_client.emit_license_fee.assert_not_called()
        task.metrics.set_outbox_breaker_open.assert_called_with(True)


class TestBudgetAndKillSignal:
    def test_stops_once_the_time_budget_is_spent(self):
        """time.monotonic() is called once for the deadline, once at the top of the
        outer loop before fetching the batch, then once per row inside it: the first
        row's check (still under budget) lets it through, the second row's check
        (over budget) stops the drain before it is even attempted."""
        task = _make_task()
        rows = [_make_row(job_id=f"job-{i}", license_fee_required=False) for i in range(3)]

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
            patch(f"{_MOD}.time.monotonic", side_effect=[0.0, 0.0, 0.0, 0.6]),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 500
            _configure_pending(mock_job_outbox, billing_event_pks=[r.pk for r in rows], rows=rows)

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
            _configure_pending(mock_job_outbox, billing_event_pks=[r.pk for r in rows], rows=rows)

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 1


class TestMultipleBatches:
    def test_keeps_fetching_batches_until_none_are_left(self):
        """A healthy Kafka should drain everything pending within the time budget,
        not just the first batch: once a batch comes back empty there is nothing
        left to send, and the outer loop stops on its own without needing the
        time budget to cut it off."""
        task = _make_task()
        row_a = _make_row(job_id="job-a", license_fee_required=False)
        row_b = _make_row(job_id="job-b", license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 500
            _configure_pending(
                mock_job_outbox,
                billing_event_pks=[row_a.pk, row_b.pk],
                batches=[[row_a], [row_b]],
            )

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 2
        row_a.save.assert_called_once()
        row_b.save.assert_called_once()

    def test_stops_between_batches_when_kill_signal_received(self):
        task = _make_task()
        row_a = _make_row(job_id="job-a", license_fee_required=False)
        row_b = _make_row(job_id="job-b", license_fee_required=False)

        def receive_after_first_batch(*_args, **_kwargs):
            task.kill_signal.received = True
            return MagicMock()

        task.event_streams_client.emit_job_completed.side_effect = receive_after_first_batch

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 500
            _configure_pending(
                mock_job_outbox,
                billing_event_pks=[row_a.pk, row_b.pk],
                batches=[[row_a], [row_b]],
            )

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 1


class TestDeletion:
    def test_issues_a_conditional_delete_for_the_row(self):
        """Deletion is a single DELETE ... WHERE carrying ready_to_delete()'s predicate,
        not a separate exists() check followed by a conditional delete(): whether the
        row actually goes away is entirely up to the SQL WHERE clause, not a Python
        branch, so there is nothing here to test beyond "the call happens"."""
        task = _make_task()
        row = _make_row(license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])

            task.run()

        mock_job_outbox.objects.ready_to_delete.return_value.filter.assert_called_once_with(pk=row.pk)
        mock_job_outbox.objects.ready_to_delete.return_value.filter.return_value.delete.assert_called_once_with()


class TestEligibilityFromQuerySetMembership:
    def test_a_row_pulled_in_only_for_the_license_fee_does_not_get_a_completed_event(self):
        """Regression test for the pre-existing bug found while redesigning this loop:

        naively re-checking eligibility from the row's own fields (e.g.
        "billing_sent_at is None") would also be true for a row included only
        because it owes the license fee while still RUNNING, and would wrongly
        send a completed event for a job that has not finished.
        """
        task = _make_task()
        row = _make_row(license_fee_required=True, billing_sent_at=None)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            # The row is pending only the license fee: it is NOT in the billing
            # event pk set, even though row.billing_sent_at is None like every
            # unsent row.
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])

            task.run()

        task.event_streams_client.emit_license_fee.assert_called_once()
        task.event_streams_client.emit_job_completed.assert_not_called()

    def test_a_row_pulled_in_only_for_the_billing_event_does_not_get_a_license_fee(self):
        """Symmetric case: a job cancelled in queue never owed the license fee."""
        task = _make_task()
        row = _make_row(license_fee_required=True, license_fee_sent_at=None)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            # The row is pending only the billing event: it is NOT in the license
            # fee pk set, even though license_fee_required=True and
            # license_fee_sent_at is None like any job that owes the fee.
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])

            task.run()

        task.event_streams_client.emit_job_completed.assert_called_once()
        task.event_streams_client.emit_license_fee.assert_not_called()
