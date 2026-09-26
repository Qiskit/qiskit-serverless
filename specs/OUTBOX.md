# Job outbox

This document describes the transactional outbox that publishes best-effort messages
to external systems in a deferred way. Today the only channel is `billing`, which
publishes two Fleets job billing facts to Kafka: the provider license fee and the
job's final usage event. The design is generic: a later PR is expected to add a
`workload` channel that mirrors job state to NTC's Runtime API, and it will not need any
change to the table or the drain task, only a new sender plus a builder that enqueues
that channel's rows (see "Adding a channel" below).

This is the canonical, committed reference for the outbox. Module docstrings in the
code point here first; a local, uncommitted design document with the original
rationale and alternatives considered may still exist on a given machine, but it is
not something other contributors can rely on.

## The problem it solves

Before this feature, the two billing events were published to Kafka inline, at the
moment a job changed status. That ties a status transition to an external system: if
Kafka is unavailable the event is dropped and the job is never billed, and a slow
broker holds up the status transition itself. The outbox decouples them: a row is
written in the same database transaction as the status change, and a separate
scheduler task drains it later, retrying for as long as it takes. A Kafka outage now
delays billing instead of losing it.

Only the license fee and the final usage event go through the outbox. The other two
Kafka events a Fleets job produces, `job_started` and `job_in_progress` (the ongoing
classical-compute-time metering, sent from `UpdateFleetsJobsStatuses`), are unrelated
to this system and are still published inline, synchronously, by
`KafkaEventStreamsClient`.

## What a row is

`Outbox` (`gateway/core/models.py`) is one row per pending message, not one row per
job: a job can have zero, one, or several rows at once, each with its own payload and
channel, deleted independently once its own send succeeds.

- `job`: a `ForeignKey` to `Job`. Delivery never uses it, the payload is
  self-contained (it carries the job's id and instance CRN inside), so a sender never
  needs to re-read the `Job` to send a message. It exists only so a pending row can
  be found from its job (admin, debugging).
- `channel`: a plain string (`"billing"` today), not a Django `choices=` field.
  Registering a new channel is adding an entry to the `{channel: sender}` dict
  `DrainOutbox` holds, not a migration.
- `payload`: a `JSONField` holding the message exactly as it will be sent. The table
  does not know what the payload means or how it was built, only that it needs to go
  out.
- `created`: set once, at insert (`auto_now_add`), used to drain oldest first and to
  measure how long a row has been waiting.

A composite index on `(channel, created)` backs the drain query, which always
filters by `channel` and orders by `created`.

A row is deleted as soon as it is sent successfully. There is no history of what was
already sent in this table.

## When a row is created: `Job.change_status`

Every status transition, everywhere in the codebase, goes through one method,
`Job.change_status`. In a single database transaction it creates the `JobEvent`,
enqueues whichever outbox messages this transition owes, and only then updates the
`Job` row itself.

A row is only ever created on a transition to a terminal status (`SUCCEEDED`,
`FAILED`, `STOPPED`), and only for a job eligible for the outbox pipeline at all:
`_eligible_for_outbox()` requires the job to run on **Fleets** (not Ray, which is
being removed and never gets a row), to **not** be a filler job, and to carry an
**instance CRN**. Nothing is built or enqueued on the transition to `RUNNING`.

`change_status` makes exactly one query to decide eligibility and to supply content
for both messages: `JobEvent.objects.first_running_at(job.id)`. This single query
answers two questions at once, so there is no separate flag to track "did this job
run" and no second query to find out.

### Did the job run: the rule that decides the license fee message

The final usage event (`build_billing_event_message`) is always built on an eligible
terminal transition, whatever the outcome: even a job cancelled while still queued
gets one, reporting zero usage seconds.

The license fee message (`build_license_fee_message`) is only built when the job is
known to have run:

- On a transition to `SUCCEEDED`, the job ran by definition, so the builder is always
  called (with `running_started_at`, which can still be `None` if the job went
  straight from queued to succeeded between two scheduler polls).
- On a transition to `FAILED` or `STOPPED`, the builder is only called when
  `first_running_at()` returned a value, that is, the job passed through `RUNNING` at
  least once before failing or being stopped.

Both builders live in `gateway/core/domain/billing_events.py` and are pure: they take
`job`, the just-created `JobEvent`, and `running_started_at`, and return a dict (or
`None`), without querying the database themselves. `build_license_fee_message` returns
`None` silently in two cases that are both treated as "this function owes no fee": the
function has no provider, or its `Program` has itself been deleted (`SET_NULL`) so
whether it had a provider can no longer even be checked. It returns `None` after
logging an error only in a third case, when the `Program` and its provider are both
still there but `job.function_size` is missing, an anomaly rather than a normal case.

Each builder that returns a message becomes one `Outbox.objects.create(job=job,
channel="billing", payload=message)` call, inside the same transaction as the status
change.

The message's CloudEvents `id` and `time` are generated when the message is built,
not when it is sent, so a retry after a Kafka outage sends the exact same bytes every
time. The Kafka topic name (the envelope's `type` field) is the one exception: it is
added later, by the sender, at send time, because it is only known once
`KafkaProducers` is instantiated.

## Drain: `DrainOutbox`, one drain per channel

`DrainOutbox` (`gateway/scheduler/tasks/drain_outbox.py`), wired into the scheduler
loop in `gateway/scheduler/main.py`, holds a `{channel: sender}` registry
(`{"billing": KafkaOutboxSender()}` today, or `NoOpOutboxSender()` when
`EVENT_STREAMS_ENABLED` is false) and drains every registered channel on every tick,
each independently, with **its own** circuit breaker and its own time budget. This is
deliberate: when a `"workload"` channel is added, a Kafka outage must not open the
breaker for `"workload"`, and vice versa.

For each channel, once a tick, the task drains successive small batches (`BATCH_SIZE
= 100` rows, a code constant, not a `Config` entry: it bounds a single query, not
throughput) oldest first, until either nothing is left pending, the tick's time
budget runs out, or the channel's breaker opens. A row that fails without tripping
the breaker, or that is unroutable, is tracked for the rest of that call so the same
row is not retried in a hot loop within one tick; it is picked up again on the next
tick.

For each row, the channel's sender receives the payload exactly as stored
(`sender.send(row.payload)`) and knows nothing about `Job`, billing, or licensing. A
successful send deletes the row unconditionally: unlike the old design, there is
nothing left to re-check, because a row is now exactly one message, and sending it is
the only thing it was waiting for. A failure leaves the row for the next tick and
feeds the channel's breaker.

`KafkaOutboxSender` (`gateway/core/ibm_cloud/event_streams/kafka_outbox_sender.py`)
is the `"billing"` sender: it adds the Kafka topic name to the payload's `type` field
and publishes it via `KafkaProducers`, the same region-routing and produce/flush logic
the old inline path used, but without building anything itself.

## Circuit breaker

Each channel gets its own `CircuitBreaker` (`gateway/scheduler/tasks/circuit_breaker.py`).
While a channel's breaker is open, no batch is fetched and no send is attempted for
that channel for the rest of the tick.

- The failure counter is **not** reset between ticks. Failures accumulate across as
  many ticks as it takes to reach the threshold (5 consecutive failures by default),
  whether they land in one tick or are spread across several.
- The only thing that resets the counter to zero is a successful send. Without one in
  between, failures keep adding up indefinitely.
- Once open, it stays open for a fixed pause (60 seconds by default), measured in
  real wall-clock time from the moment it opened, regardless of how many scheduler
  ticks pass meanwhile.
- It closes itself the next time anything asks whether it is open, once that pause
  has elapsed, and the failure counter resets to zero as if nothing had happened.
  Closing does not carry any memory forward: a fresh, uninterrupted streak of
  failures is needed to open it again.
- The breaker is checked not only once before the tick starts, but again before every
  batch and before every row within a batch, so a failure that trips it mid-tick
  stops the rest of that channel's work immediately instead of only from the next
  tick onward.

`OUTBOX_BREAKER_FAILURES` and `OUTBOX_BREAKER_PAUSE_SECONDS` are read lazily through
callables passed into the breaker, so they can change at runtime through `Config`
without recreating the breaker or restarting the process.

## Configuration and observability

Everything except the batch size is a `Config` entry (admin-editable, no redeploy
needed): `scheduler.outbox.enabled` (kill switch, off by default),
`scheduler.outbox.budget_ms` (default 500), `scheduler.outbox.breaker_failures`
(default 5), `scheduler.outbox.breaker_pause_seconds` (default 60). These are global
across all channels for now, since only `"billing"` uses them; a future channel that
needs different thresholds gets its own `Config` keys without touching these.

Prometheus metrics:

- `scheduler_outbox_sends_total{fact,outcome}`: one increment per send attempt. `fact`
  is billing-specific vocabulary (`license_fee` or `billing_event`), read from the
  payload's `data.metric_type` prefix, not from a dedicated column. A future
  non-billing channel either reports no fact split or adds its own case; nothing
  about delivery itself depends on this label.
- `scheduler_outbox_pending_rows{fact}` and
  `scheduler_outbox_oldest_pending_age_seconds{fact}`: reported every tick for every
  registered channel, independent of whether that channel's breaker is open. For
  `"billing"` these still split by fact (`license_fee`, `billing_event`) using the
  same payload-content filter; any other channel reports one count under its own
  channel name as the label.
- `scheduler_outbox_breaker_open{channel}`: whether a given channel's breaker is
  currently open. This carries a `channel` label precisely because there is now one
  breaker per channel, not one breaker overall.

The old `scheduler_outbox_license_fee_irrecoverable_total` counter is gone. The one
case it measured that is still an anomaly today, a licensed function whose
`FunctionSize` has been deleted, is not impossible, but the race window that causes
it shrank from "the whole time a row sat in the outbox" to "the duration of one
database transaction" once messages are built inside `change_status` rather than at
send time. It is now visible only through a `logger.error(...)` call from
`build_license_fee_message`, not through a metric: `core` cannot import
`SchedulerMetrics` from `scheduler`, and `import-linter` enforces that boundary. A
deleted `Program` (so a function with no known provider) is not part of this: it is
treated as the normal "this job owes no fee" case, silently, with no log line at all.

## Adding a channel

Adding a channel needs no schema change and no change to `DrainOutbox`'s draining
logic. It needs:

1. A builder that decides when to enqueue a message for that channel and calls
   `Outbox.objects.create(job=job, channel="<name>", payload=message)`, wherever in
   the codebase that channel's fact becomes true.
2. A sender class with a `send(payload)` method, registered under its own key in
   `DrainOutbox.senders`.

The `"workload"` channel, mirroring job state to NTC's Runtime API, is expected to be
exactly this: one more sender and one more registry entry, with its own `Config` keys
if its thresholds need to differ from `"billing"`'s.
