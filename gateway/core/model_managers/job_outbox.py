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
            AND has_run = true

        `license_fee_required` + `license_fee_sent_at` NULL = fees not sent yet

        `license_fee_required` is false when the function has no provider: those jobs
        never owe a fee, and without this term they would read as pending forever.

        `has_run` is the proof that the job executed, which is what the fee pays for.
        The row is created while the job is still queued, so without this term it would
        read as pending from the moment it exists. add_status_event sets it, on RUNNING
        and on SUCCEEDED.

        A job that jumps from PENDING straight to FAILED or STOPPED leaves has_run false
        and is not charged: those two states prove nothing on their own, and a job that
        never started (submission failed, or cancelled in queue) must not pay. So the fee
        is lost when the job really did run, but only for a run short enough to fit
        between two scheduler polls.

        A job that ran and then failed does owe the fee here. If that policy ever
        becomes "only successful jobs pay", this predicate is the only rule to
        edit, but ready_to_delete() mirrors its negation by hand and has to be
        edited with it.
        """
        return self.filter(license_fee_required=True, license_fee_sent_at__isnull=True, has_run=True)

    def pending_billing_event(self):
        """Rows whose final usage event has not been sent yet.

        Pseudo-SQL:
            billing_sent_at IS NULL
            AND job_status IN ('SUCCEEDED', 'FAILED', 'STOPPED')

        The terminal state is the term that matters here, no matter which one it is: this
        event has to carry final usage, and `has_run` stays true while the job is still
        RUNNING, so it cannot tell a finished job from a live one.

        `has_run` is left out on purpose. Adding it would only drop the jobs that never
        ran, and those are harmless: `_usage_seconds` returns zero when the job has no
        RUNNING event, so a job cancelled in queue reports zero seconds instead of a wrong
        figure. Unlike the license fee, nothing is charged for merely having existed.
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
                OR has_run = false
            )
            AND billing_sent_at IS NOT NULL

        The terminal gate matters on its own: without it, a job that simply has
        not yet reached the point where a fact would apply (still QUEUED, or
        RUNNING with no license fee due) reads as vacuously "nothing pending" and
        would be deleted while still alive.

        The license fee clause is pending_license_fee()'s three terms negated by
        hand, so the two definitions have to be edited together. Dropping the
        third term (a job that never ran because it was cancelled in queue or
        failed to submit) once left those rows permanently pending: they never
        owed the fee, but they did not satisfy either of the other two branches
        either, so they were never deleted. Found in adversarial review, see spec
        section 5.2.

        The mirror clause (workload_status) is added in the second PR, once a
        task reads and writes it; until then it plays no part in this query (see
        spec section 9's note on the two-PR rollout).
        """
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        terminal = Q(job_status__in=Job.TERMINAL_STATUSES)
        license_fee_settled = Q(license_fee_required=False) | Q(license_fee_sent_at__isnull=False) | Q(has_run=False)
        billing_event_settled = Q(billing_sent_at__isnull=False)
        return self.filter(terminal & license_fee_settled & billing_event_settled)
