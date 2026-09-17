"""Job outbox model manager.

Query predicates for the two billing facts this PR tracks (the license fee and
the final usage event). The mirror's predicate is added in the second PR.
"""

from django.db.models import Q, QuerySet


class JobOutboxQuerySet(QuerySet):
    """Query helpers for JobOutbox rows."""

    def pending_license_fee(self):
        """Rows whose license fee is owed and has not been sent yet.

        Pseudo-SQL:
            license_fee_required = true
            AND license_fee_sent_at IS NULL
            AND (has_run = true OR job_status = 'SUCCEEDED')

        `license_fee_required` drops jobs whose program has no provider: they
        never owe a fee, so without this term they would read as pending forever.
        `has_run OR SUCCEEDED` closes the gap where status polling jumps straight
        from PENDING to SUCCEEDED without the job ever being observed in RUNNING:
        it still executed, so it owes the fee, whereas a job cancelled in queue or
        one whose submission failed (FAILED/STOPPED without having run) does not.
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(
            Q(license_fee_required=True, license_fee_sent_at__isnull=True)
            & (Q(has_run=True) | Q(job_status=Job.SUCCEEDED))
        )

    def pending_billing_event(self):
        """Rows whose final usage event has not been sent yet.

        Pseudo-SQL:
            billing_sent_at IS NULL
            AND job_status IN ('SUCCEEDED', 'FAILED', 'STOPPED')

        Unlike the license fee, this is owed regardless of whether the job ever
        ran: usage seconds are computed from running_started_at and
        status_changed_at, and come out as zero for a job that never reached
        RUNNING, so sending the event for a job cancelled in queue is harmless.
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(billing_sent_at__isnull=True, job_status__in=Job.TERMINAL_STATUSES)

    def ready_to_delete(self):
        """Rows where every fact this PR tracks is settled.

        Pseudo-SQL:
            job_status IN ('SUCCEEDED', 'FAILED', 'STOPPED')
            AND (
                license_fee_required = false
                OR license_fee_sent_at IS NOT NULL
                OR (has_run = false AND job_status != 'SUCCEEDED')
            )
            AND billing_sent_at IS NOT NULL

        The terminal gate matters on its own: without it, a job that simply has
        not yet reached the point where a fact would apply (still QUEUED, or
        RUNNING with no license fee due) reads as vacuously "nothing pending" and
        would be deleted while still alive.

        The license fee clause is the full negation of pending_license_fee's
        three terms, not just the first two. Dropping the third term (a job that
        never ran because it was cancelled in queue or failed to submit) once
        left those rows permanently pending: they never owed the fee, but they
        did not satisfy either of the other two branches either, so they were
        never deleted. Found in adversarial review, see spec section 5.2.

        The mirror clause (workload_status) is added in the second PR, once a
        task reads and writes it; until then it plays no part in this query (see
        spec section 9's note on the two-PR rollout).
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        terminal = Q(job_status__in=Job.TERMINAL_STATUSES)
        license_fee_settled = (
            Q(license_fee_required=False)
            | Q(license_fee_sent_at__isnull=False)
            | (Q(has_run=False) & ~Q(job_status=Job.SUCCEEDED))
        )
        billing_event_settled = Q(billing_sent_at__isnull=False)
        return self.filter(terminal & license_fee_settled & billing_event_settled)
