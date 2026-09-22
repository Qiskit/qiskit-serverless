"""Job outbox model manager.

Query predicates for the billing facts a row can owe. What creates a row, how its flags
get set and how rows are dispatched are all in specs/OUTBOX.md.
"""

from django.db.models import Q, QuerySet


class JobOutboxQuerySet(QuerySet):
    """Query helpers for JobOutbox rows."""

    def pending_license_fee(self):
        """Rows whose license fee is owed and has not been sent yet.

        Pseudo-SQL:
            license_fee_required = true
            AND license_fee_sent_at IS NULL
            AND has_run = true

        `license_fee_required` is false when the function has no provider: those jobs never
        owe a fee, and without this term they would read as pending forever. `has_run` is
        the proof that the job executed, which is what the fee pays for, and
        Job.change_status sets it on the transition to RUNNING or to SUCCEEDED.

        So a job that jumps from PENDING straight to FAILED or STOPPED is never charged,
        and a run short enough to fit between two scheduler polls before failing goes
        unbilled. That is the intended trade: neither state proves the job ever started,
        and charging one that did not is the worse mistake.
        """
        return self.filter(license_fee_required=True, license_fee_sent_at__isnull=True, has_run=True)

    def pending_billing_event(self):
        """Rows whose final usage event has not been sent yet.

        Pseudo-SQL:
            billing_sent_at IS NULL
            AND job_status IN ('SUCCEEDED', 'FAILED', 'STOPPED')

        The terminal status is the only term that matters: this event carries final usage,
        and `has_run` stays true while the job is still RUNNING, so it cannot tell a
        finished job from a live one. Leaving `has_run` out costs nothing, because
        `_usage_seconds` reports zero for a job that has no RUNNING event.
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(billing_sent_at__isnull=True, job_status__in=Job.TERMINAL_STATUSES)

    def ready_to_delete(self):
        """Rows where every fact is settled, so nothing will ever be sent for them again.

        Pseudo-SQL:
            job_status IN ('SUCCEEDED', 'FAILED', 'STOPPED')
            AND (
                license_fee_required = false
                OR license_fee_sent_at IS NOT NULL
                OR has_run = false
            )
            AND billing_sent_at IS NOT NULL

        The terminal gate matters on its own: without it, a job that has not yet reached
        the point where a fact would apply (still QUEUED, or RUNNING with no fee due) reads
        as vacuously settled and would be deleted while still alive.

        The license fee clause is pending_license_fee()'s three terms negated by hand, in a
        second place, so the two have to be edited together. A past review found a bug from
        a term missing here.
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        terminal = Q(job_status__in=Job.TERMINAL_STATUSES)
        license_fee_settled = Q(license_fee_required=False) | Q(license_fee_sent_at__isnull=False) | Q(has_run=False)
        billing_event_settled = Q(billing_sent_at__isnull=False)
        return self.filter(terminal & license_fee_settled & billing_event_settled)
