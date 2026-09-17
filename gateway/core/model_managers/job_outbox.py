"""Job outbox model manager.

Query predicates for the two billing facts this PR tracks (the license fee and
the final usage event). The mirror's predicate is added in the second PR. See
.claude/specs/2026-09-16-job-outbox-design.md sections 5.1 and 5.2.
"""

from django.db.models import Q, QuerySet


class JobOutboxQuerySet(QuerySet):
    """Query helpers for JobOutbox rows."""

    @staticmethod
    def _license_fee_pending_q() -> Q:
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return Q(license_fee_required=True, license_fee_sent_at__isnull=True) & (
            Q(has_run=True) | Q(job_status=Job.SUCCEEDED)
        )

    @staticmethod
    def _billing_event_pending_q() -> Q:
        from core.models import Job  # pylint: disable=import-outside-toplevel, cyclic-import

        return Q(billing_sent_at__isnull=True, job_status__in=Job.TERMINAL_STATUSES)

    def pending_license_fee(self):
        """Rows whose license fee is owed and has not been sent yet."""
        return self.filter(self._license_fee_pending_q())

    def pending_billing_event(self):
        """Rows whose final usage event has not been sent yet."""
        return self.filter(self._billing_event_pending_q())

    def pending_kafka_outbox(self, limit: int):
        """Rows owing a license fee or a final usage event, oldest status change first."""
        return self.filter(self._license_fee_pending_q() | self._billing_event_pending_q()).order_by(
            "status_changed_at"
        )[:limit]

    def ready_to_delete(self):
        """Rows where every fact this PR tracks is settled.

        Gated on the job being terminal: without that gate, a job that simply has
        not yet reached the point where a fact would apply (still QUEUED, or
        RUNNING with no license fee due) reads as vacuously "nothing pending" and
        would be deleted while still alive. The mirror clause is added in the
        second PR, once workload_status is read and written by a task; until
        then it plays no part in this query (see spec section 9's note on the
        two-PR rollout).
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
