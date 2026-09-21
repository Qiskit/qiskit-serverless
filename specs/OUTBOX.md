# Job outbox

This document describes the transactional outbox that publishes two Fleets job billing
facts to Kafka: the provider license fee and the job's final usage event.

## The problem it solves

Before this feature, these two events were published to Kafka inline, at the moment a job
changed status. That ties a status transition to an external system: if Kafka is
unavailable the event is dropped and the job is never billed, and a slow broker holds up
the status transition itself. The outbox decouples them: a row is written in the same
database transaction as the status change, and a separate scheduler task drains it later,
retrying for as long as it takes. A Kafka outage now delays billing instead of losing it.

Only these two facts go through the outbox. The other two Kafka events a Fleets job
produces, `job_started` and `job_in_progress` (the ongoing classical-compute-time
metering, sent from `UpdateFleetsJobsStatuses`), are unrelated to this PR and are still
published inline, synchronously, unchanged.

## What creates a row, and when

A `JobOutbox` row is created once, at job submission
(`api/use_cases/programs/run.py`), and only for jobs that can actually reach the outbox
pipeline: the function must run on **Fleets** (not Ray, which is being removed and never
gets a row), the job must **not** be a filler job, and it must carry an **instance CRN**.
`JobOutbox.job` is a `OneToOneField` to `Job` and doubles as its primary key, so there can
never be more than one row per job, and `row.pk` is the job's own id.

At creation, `license_fee_required` is set from whether the function has a provider
(`function.provider_id is not None`): a function with no provider never owes a fee. Two
more fields track state as the job progresses: `has_run`, which starts `False`, and
`job_status` / `status_changed_at`, which mirror the job's own status and its timestamp.

## How the flags get set: `Job.change_status`

Every status transition, everywhere in the codebase, goes through one method:
`Job.change_status`. In a single database transaction it: creates the `JobEvent`, updates
the matching `JobOutbox` row (if one exists) with the new `job_status` and
`status_changed_at`, and finally updates the `Job` row itself. Because the outbox update
is a plain `queryset.update()` filtered by `job_id`, it silently matches nothing for a
job that has no row (filler, Ray, or missing CRN) instead of needing a separate check.

`has_run` is set to `True` on the transition to **either RUNNING or SUCCEEDED**, and never
cleared again. Both transitions matter: RUNNING is the common case, but a job that starts
and finishes between two scheduler polls is only ever observed going straight from PENDING
to SUCCEEDED, so SUCCEEDED is the only place that would ever record that it ran. A job
that jumps straight to FAILED or STOPPED without ever passing through either of those two
leaves `has_run` false and never pays the license fee, because neither of those two states
proves the job actually started.

## What each row owes, and when it is dispatched

Two independent predicates decide what a row still owes (`core/model_managers/job_outbox.py`):

- **License fee pending**: `license_fee_required` is true, `license_fee_sent_at` is still
  null, and `has_run` is true. A row becomes eligible the moment the job starts running
  (or, for a very short job, the moment it succeeds), regardless of how the job ends later.
- **Final usage event pending**: `billing_sent_at` is still null and the job has reached a
  terminal status (`SUCCEEDED`, `FAILED`, `STOPPED`). This one does not require `has_run`:
  a job cancelled in queue still gets a completed event, just reporting zero usage seconds.

A row can owe one fact, both, or neither at a given moment; it is picked up as soon as
either predicate is true, and it keeps being picked up on every scheduler tick until both
are settled. Once every fact the row could ever owe is settled (the fee is either not
required, sent, or the job never ran; and the usage event is sent), the row is deleted.

## Dispatch: the `PublishOutbox` scheduler task

Once a tick, the task drains the outbox in successive small batches (100 rows each),
oldest first, until either nothing is left pending or the tick's time budget (500ms by
default) runs out. A healthy Kafka is expected to drain everything in one tick; the batch
size only bounds a single query, it is not the throughput cap.

For each row, sending each owed fact is independent: a license fee failure does not block
that row's usage event, and vice versa. A successful send stamps that fact's `_sent_at`
with the current time; the row is saved once per row (not once per fact), and then a
single conditional `DELETE ... WHERE` attempts to remove it, which only succeeds once it
is actually fully settled.

A license fee send that fails because the job's function or provider was deleted
(`AttributeError`, both are nullable foreign keys) is treated as unrecoverable: the row is
abandoned rather than retried forever, and it is only visible through a metric.

## Circuit breaker

An in-memory, per-task circuit breaker protects the drain from a Kafka outage: while it is
open, no batch is fetched and no send is attempted at all for the rest of that tick.

- The failure counter is **not** reset between ticks. Failures accumulate across as many
  ticks as it takes to reach the threshold (5 consecutive failures by default), whether
  they land in one tick or are spread across several.
- The only thing that resets the counter to zero is a successful send. Without one in
  between, failures keep adding up indefinitely.
- Once open, it stays open for a fixed pause (60 seconds by default), measured in real
  wall-clock time from the moment it opened, regardless of how many scheduler ticks pass
  meanwhile.
- It closes itself the next time anything asks whether it is open, once that pause has
  elapsed, and the failure counter resets to zero as if nothing had happened. Closing does
  not carry any memory forward: a fresh, uninterrupted streak of failures is needed to
  open it again.
- The breaker is checked not only once before the tick starts, but again before every
  batch and before every row within a batch, so a failure that trips it mid-tick stops the
  rest of that tick's work immediately instead of only from the next tick onward.

Values are read once, at task construction (`OUTBOX_BREAKER_FAILURES`,
`OUTBOX_BREAKER_PAUSE_SECONDS`); they are not re-read per tick like the other outbox knobs.

## Configuration and observability

Everything except the batch size is a `Config` entry (admin-editable, no redeploy needed):
`scheduler.outbox.enabled` (kill switch, off by default), `scheduler.outbox.budget_ms`,
`scheduler.outbox.breaker_failures`, `scheduler.outbox.breaker_pause_seconds`. The batch
size is a plain code constant (`BATCH_SIZE = 100` in `publish_outbox.py`): it bounds query
size, not throughput, so there is nothing an operator would tune during an incident.

Prometheus metrics: `scheduler_outbox_sends_total{fact,outcome}`,
`scheduler_outbox_license_fee_irrecoverable_total`, `scheduler_outbox_pending_rows{fact}`
and `scheduler_outbox_oldest_pending_age_seconds{fact}` (both reported every tick,
independent of whether the breaker is open), and `scheduler_outbox_breaker_open`.

## Technical details worth knowing

- **The outbox row update in `change_status` never writes `job_status` back from a copy
  the caller already has**: it always reads the just-created `JobEvent`'s own
  `status`/`created` fields, so the row's timestamp can never disagree with the event that
  justifies it.
- **`_process_row` scopes its two eligibility sets to the current batch**, not to the
  whole pending backlog: it queries `pending_license_fee()`/`pending_billing_event()`
  filtered by the batch's own primary keys, rather than re-deriving eligibility from a
  row's own fields (which would wrongly treat a row pending only the license fee, while
  still `RUNNING`, as also owing a completed event).
- **`ready_to_delete()`'s "license fee settled" clause is `pending_license_fee()`'s three
  terms negated by hand**, in a second place. The two must be kept in sync by hand; a past
  review found a bug from a missing term here.
- **The mirror to the Runtime API (`workload_status`) is out of scope for this PR.** The
  column already exists on the model, but nothing writes or reads it yet; a follow-up PR
  reuses this same task and these same metrics for that second fact.
- **Ray jobs are excluded on purpose**, not as an oversight: Ray is being removed, so no
  outbox row is ever created for one.
- **`stop.py`'s job status write now goes through `change_status`**, and therefore through
  `Job.update_fields`, which bypasses `django-concurrency`'s optimistic-locking check that
  a plain `job.save()` used to enforce there.
