"""Unit tests for PublishOutbox."""

from datetime import datetime, timezone
from itertools import chain, repeat
from unittest.mock import MagicMock, call, patch

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as dj_timezone

from core.ibm_cloud.event_streams.kafka_event_streams_client import UnroutableRegionError
from core.models import Job, JobOutbox, Program, Provider
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
    """A row's job has a program and a provider by default (both auto-created MagicMocks,
    so neither is None), matching the common case where the license fee payload can be
    built. Pass `row.job.program = None` (or `row.job.program.provider = None`) after
    construction to exercise the waiver path.
    """
    row = MagicMock()
    row.pk = job_id
    row.job_id = job_id
    row.job = MagicMock()
    row.license_fee_required = license_fee_required
    row.license_fee_sent_at = license_fee_sent_at
    row.billing_sent_at = billing_sent_at
    row.status_changed_at = status_changed_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
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
    combined.select_related.return_value.order_by.return_value.__getitem__.side_effect = chain(
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
    def test_sends_license_fee_and_billing_event_and_writes_both_via_update(self):
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
        mock_job_outbox.objects.filter.assert_called_once_with(pk=row.pk)
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(
            license_fee_sent_at=now, billing_sent_at=now
        )

    def test_skips_license_fee_when_not_required(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_license_fee.assert_not_called()
        task.event_streams_client.emit_job_completed.assert_called_once()
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(billing_sent_at=now)

    def test_skips_billing_event_when_already_sent(self):
        task = _make_task()
        already_sent = datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        row = _make_row(license_fee_required=True, billing_sent_at=already_sent)

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])
            now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_job_completed.assert_not_called()
        task.event_streams_client.emit_license_fee.assert_called_once()
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(license_fee_sent_at=now)


class TestFailureHandling:
    def test_network_failure_does_not_write_anything_and_records_failure_on_the_breaker(self):
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

        task._breaker.record_failure.assert_called_once()
        mock_job_outbox.objects.filter.assert_not_called()

    def test_license_fee_unroutable_region_does_not_trip_the_breaker(self):
        task = _make_task()
        row = _make_row(license_fee_required=True)
        task.event_streams_client.emit_license_fee.side_effect = UnroutableRegionError("no producer for region")

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])

            task.run()

        task._breaker.record_failure.assert_not_called()
        task.metrics.increment_outbox_send.assert_any_call("license_fee", "unroutable")
        mock_job_outbox.objects.filter.assert_not_called()

    def test_billing_event_unroutable_region_does_not_trip_the_breaker(self):
        task = _make_task()
        row = _make_row(license_fee_required=False)
        task.event_streams_client.emit_job_completed.side_effect = UnroutableRegionError("no producer for region")

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, billing_event_pks=[row.pk], rows=[row])

            task.run()

        task._breaker.record_failure.assert_not_called()
        task.metrics.increment_outbox_send.assert_any_call("billing_event", "unroutable")
        mock_job_outbox.objects.filter.assert_not_called()

    def test_license_fee_waived_when_program_is_missing_and_does_not_block_the_billing_event(self):
        task = _make_task()
        row = _make_row(license_fee_required=True)
        row.job.program = None

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], billing_event_pks=[row.pk], rows=[row])
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_license_fee.assert_not_called()
        task.metrics.increment_outbox_license_fee_irrecoverable.assert_called_once()
        task.event_streams_client.emit_job_completed.assert_called_once()
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(
            license_fee_required=False, billing_sent_at=now
        )
        task._breaker.record_failure.assert_not_called()

    def test_license_fee_waived_when_provider_is_missing(self):
        task = _make_task()
        row = _make_row(license_fee_required=True)
        row.job.program.provider = None

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_license_fee.assert_not_called()
        task.metrics.increment_outbox_license_fee_irrecoverable.assert_called_once()
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(license_fee_required=False)

    def test_license_fee_waived_when_function_size_is_missing(self):
        """function_size is a SET_NULL foreign key too: a FunctionSize row deleted after
        the job was submitted reaches this same null state, past the point where
        run.py's submission-time check could have caught it."""
        task = _make_task()
        row = _make_row(license_fee_required=True)
        row.job.function_size = None

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone") as mock_timezone,
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            mock_timezone.now.return_value = now

            task.run()

        task.event_streams_client.emit_license_fee.assert_not_called()
        task.metrics.increment_outbox_license_fee_irrecoverable.assert_called_once()
        mock_job_outbox.objects.filter.return_value.update.assert_called_once_with(license_fee_required=False)

    def test_unexpected_attribute_error_from_the_client_propagates(self):
        """AttributeError is no longer caught here: a stray one from a real bug (program
        and provider are both present) must not be silently treated as irrecoverable."""
        task = _make_task()
        row = _make_row(license_fee_required=True)
        task.event_streams_client.emit_license_fee.side_effect = AttributeError("some real bug")

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 20
            _configure_pending(mock_job_outbox, license_fee_pks=[row.pk], rows=[row])

            with pytest.raises(AttributeError):
                task.run()

        task.metrics.increment_outbox_license_fee_irrecoverable.assert_not_called()

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

    def test_stops_within_the_same_batch_once_the_breaker_opens_mid_tick(self):
        """The breaker is only checked once before the outer loop starts. If a failure
        trips it while a batch is being processed, the drain must not keep attempting
        further rows in that same batch: this is a regression test for that gap."""
        task = _make_task()
        rows = [_make_row(job_id=f"job-{i}", license_fee_required=False) for i in range(2)]

        def fail_and_open_breaker(*_args, **_kwargs):
            task._breaker.is_open = True
            raise RuntimeError("kafka down")

        task.event_streams_client.emit_job_completed.side_effect = fail_and_open_breaker

        with (
            patch(f"{_MOD}.Config") as mock_config,
            patch(f"{_MOD}.JobOutbox") as mock_job_outbox,
            patch(f"{_MOD}.timezone"),
        ):
            mock_config.get_bool.return_value = True
            mock_config.get_int.return_value = 500
            _configure_pending(mock_job_outbox, billing_event_pks=[r.pk for r in rows], rows=rows)

            task.run()

        assert task.event_streams_client.emit_job_completed.call_count == 1

    def test_stops_before_the_next_batch_once_the_breaker_opens_mid_tick(self):
        """Symmetric case at the batch boundary: a breaker tripped while draining the
        first batch must stop the loop before it ever fetches a second one."""
        task = _make_task()
        row_a = _make_row(job_id="job-a", license_fee_required=False)
        row_b = _make_row(job_id="job-b", license_fee_required=False)

        def fail_and_open_breaker(*_args, **_kwargs):
            task._breaker.is_open = True
            raise RuntimeError("kafka down")

        task.event_streams_client.emit_job_completed.side_effect = fail_and_open_breaker

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
        assert mock_job_outbox.objects.filter.call_args_list == [call(pk=row_a.pk), call(pk=row_b.pk)]
        assert mock_job_outbox.objects.filter.return_value.update.call_count == 2

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
        """See _process_row's docstring for why this is a single conditional DELETE rather
        than a separate exists() check: that leaves nothing here to test beyond "the call
        happens", since whether the row actually goes away is entirely up to the SQL WHERE
        clause, not a Python branch."""
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
        """Regression test for the pre-existing bug found while redesigning this loop: see the
        comment above the pk-set computation in run() for what naively re-deriving eligibility
        from the row's own fields would have gotten wrong here."""
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


@pytest.mark.django_db
class TestFetchBatchQueryEfficiency:
    """Fix 4/5a: _fetch_batch() must not cost one extra query per row per relation."""

    def test_fetch_batch_uses_select_related_to_avoid_n_plus_one(self):
        user = User.objects.create_user(username="author")
        provider = Provider.objects.create(name="TestProvider")
        program = Program.objects.create(title="prog", author=user, provider=provider)

        for _ in range(5):
            job = Job.objects.create(
                author=user,
                program=program,
                status=Job.SUCCEEDED,
                instance_crn="crn:v1:bluemix:public:quantum-computing:us-east:a/abc:def::",
            )
            JobOutbox.objects.create(
                job=job,
                job_status=Job.SUCCEEDED,
                status_changed_at=dj_timezone.now(),
                has_run=True,
                license_fee_required=True,
            )

        with CaptureQueriesContext(connection) as ctx:
            batch = PublishOutbox._fetch_batch()
            for row in batch:
                # Access the FKs the batch will need: this must not add queries beyond
                # the single one select_related already joined.
                _ = row.job.program.provider.name

        assert len(batch) == 5
        assert len(ctx.captured_queries) <= 2
