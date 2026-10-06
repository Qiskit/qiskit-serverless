# Job outbox

This document describes the transactional outbox that publishes best-effort messages
to external systems in a deferred way. Today the only channels are `OutboxChannel.LICENSE_FEE`
(`"billing_license_fee"`) and `OutboxChannel.JOB_USAGE` (`"billing_job_usage"`), the two Fleets job
billing facts published to Kafka. The design is meant to stay generic: a later PR is expected
to add a `workload` channel that mirrors job state to NTC's Runtime API, and it will not need
any change to the table's structure or the drain task's logic, only a new `OutboxChannel`
member, a new sender plus a builder that enqueues that channel's rows, and (since `choices=`
below) a small migration (see "Adding a channel").

## The problem it solves

Before this feature, the two billing events were published to Kafka inline, at the
moment a job changed status. That ties a status transition to an external system: if
Kafka is unavailable the event is dropped and the job is never billed, and a slow
broker holds up the status transition itself. The outbox decouples them: a row is
written in the same database transaction as the status change, and a separate
scheduler task drains it later, retrying for as long as it takes. A Kafka outage now
delays billing instead of losing it.

Only the license fee and the final usage event go through the outbox. The other Kafka
event a Fleets job produces, `job_in_progress` (the ongoing classical-compute-time
metering, sent by `JobTransitionService`, with `job_started=True` on the first
one sent right after a job's `PENDING -> RUNNING` transition), is unrelated to this
system: it is built by the same builder (see below) but sent inline
right after building, instead of through a row in this table.

## Kafka events at a glance

A Fleets job produces two kinds of Kafka events:

- **Best effort**: events that can be lost. They are sent straight to Kafka from the
  scheduler, without waiting for the broker. If they arrive, good; if not, they are logged
  and dropped, and are not retried.
- **Outbox**: events that cannot be lost. They are not sent from the scheduler. A JSON
  message is written to the `outbox` table, and the `OutboxTask` scheduler task picks
  these rows up and sends them where they belong (Kafka today, later NTC workloads or
  whatever comes next). If the target system is down, the send is retried on the next
  scheduler pass.

Four events in total:

| Event | Path | When it is sent |
|---|---|---|
| Job usage, start | best effort | once, when the job moves to `RUNNING` |
| Job usage, in progress | best effort | about every second, while the job is `RUNNING` and stays `RUNNING` |
| Job usage, finished | outbox | when the job ends, whatever the terminal status (`FAILED`, `SUCCEEDED` or `STOPPED`) |
| License fee | outbox | when the job ends in `SUCCEEDED`, or in `FAILED`/`STOPPED` after having been seen in `RUNNING`, if the function has a provider and a `function_size` (see "Did the job run" below) |

## What a row is

`Outbox` (`gateway/core/models.py`) is one row per pending message, not one row per
job: a job can have zero, one, or several rows at once, each with its own payload and
channel, deleted independently once its own send succeeds.

- `job`: a `ForeignKey` to `Job`. Delivery never uses it, the payload is
  self-contained (it carries the job's id and instance CRN inside), so a sender never
  needs to re-read the `Job` to send a message. It exists only so a pending row can
  be found from its job (admin, debugging).
- `channel`: a `CharField` with `choices=` built from the `OutboxChannel` enum
  (`core/models.py`). That restricts what Django's admin/forms accept, but is not a
  database constraint: the writer and the drainer both talk to this table through a
  plain `.objects.create()`/`.filter()`, which bypasses `choices=` entirely, so
  nothing here stops a value outside the enum from being written or drained.
  Registering a new channel is adding a member to `OutboxChannel` plus an entry to
  the `{channel: Destination}` dict `OutboxTask` holds; because `choices=` is part of
  the field's migration-tracked state, that member also needs a small migration
  (`AlterField`, no data change) alongside it.
- `region`: a nullable `CharField`, the region of the job's instance CRN (parsed with `Crn.parse`)
  when the row is created, or null when the CRN has none or the channel has no such notion. Delivery
  uses it only to pick the circuit breaker, so a region that fails does not hold back the others.
  The sender does not read it: `KafkaSender` still takes the region from the payload's CRN to pick
  the cluster. Rows created before the column existed are null and are sent as one more region.
- `payload`: a `JSONField` holding the message exactly as it will be sent. The table
  does not know what the payload means or how it was built, only that it needs to go
  out.
- `created`: set once, at insert (`auto_now_add`), used to drain oldest first and to
  measure how long a row has been waiting.

A composite index on `(channel, created)` backs the pending-rows gauges, and one on
`(channel, region, created)` backs the drain, which filters by channel and region and orders by
`created`.

A row is deleted as soon as it is sent successfully. There is no history of what was
already sent in this table.

## When a row is created: `JobTransitionService`

Every status transition, everywhere in the codebase, goes through
`JobTransitionService` (`gateway/core/services/job_transitions.py`), which has one method per
transition: `queued_to_pending`, `pending_to_running`, `to_succeeded`, `to_failed` and
`to_stopped`, plus `to_terminal`, which picks one of the last three from a final status. Each one
changes the status and does what that transition owes, so a caller cannot forget it. In a single
database transaction it creates the `JobEvent`, updates the `Job` row, and enqueues whichever
outbox messages this transition owes. The best effort events (see below) are not part of that
transaction. Every method reads the current status under a row lock
(`select_for_update`) and raises `InvalidJobTransitionException` for any status not
in `JobTransitionService.VALID_TRANSITIONS[current_status]`, an already-terminal current status
included, so it never writes anything on top of one. That lock is also what makes a
race between two callers transitioning the same job safe (e.g. the scheduler
completing a job while a user-initiated stop request is in flight): the second one
to reach the lock waits for the first's transaction to commit, then reads the
post-commit status and validates its own transition against that, so it either
proceeds correctly or raises, but can never overwrite the first's final status or
create a second `JobEvent` for it. Every caller that can legitimately race this way
catches that exception itself and decides what "already terminal" means there;
`JobTransitionService` never swallows it, and nothing is enqueued or sent when it is raised.

A row is only ever created on a transition to a terminal status (`SUCCEEDED`,
`FAILED`, `STOPPED`), and only for a job eligible for the outbox pipeline at all:
`_is_usage_billable` (in `job_transitions.py`) requires the job to run on **Fleets** (not Ray, which
is being removed and never gets a row), to **not** be a filler job, and to carry an
**instance CRN**. The license fee has one more requirement, checked by `_is_fee_billable`: the
job's function has a provider. Only `to_succeeded`, `to_failed` and `to_stopped` enqueue
anything, and a job only reaches a terminal status once, so they run once per job. Nothing is
built or enqueued on the transitions to `PENDING` or `RUNNING`.

### Best effort events

The `job_started` event (sent by `pending_to_running`) and the periodic in-progress event
(`running_to_running`, not a transition: the job stays `RUNNING`, and no status or `JobEvent`
is written) do not go through the outbox. They are sent directly to Kafka with the sender of
the service, with `send(payload, timeout=0)`: the message is handed to the producer and the call returns,
without a flush, and it never raises. librdkafka delivers it in the background and gives up on it after
`message.timeout.ms`. A message that cannot be routed, queued (the producer's local queue is full) or
delivered is dropped. `KafkaSender` warns about the drops at most once per 30 seconds (the first one at once),
with how many were dropped since the last warning and the subject (job id) and error of the last one, so a
broker that is down does not write a log line per job per second.

These producers are not shared with the outbox, whose flush therefore never waits for them. Nothing flushes
them when the scheduler stops: what is still queued then is lost, which is acceptable for events that can be
lost anyway.

`pending_to_running` sends its event right after its own transaction ends, so the network
call never holds the row lock and nothing is sent for a transition that did not happen. The
service must not be called from inside another transaction: the send would not wait for the
outer one to commit. A filler job sends none.

The sender is the `sender` argument of the constructor. When none is given it is built with
`build_kafka_sender()`, which is a `NoOpSender` unless `EVENT_STREAMS_ENABLED` is true, and then
it creates the Kafka producers. The scheduler creates one service in `scheduler/main.py` and hands
it to the three tasks that change a job status, so the producers are built once. The API creates
a `JobTransitionService` per `StopJobUseCase` with no argument: the chart only sets
`EVENT_STREAMS_ENABLED` in the scheduler container, so there it gets a `NoOpSender` and sends
nothing. Enabling it in the gateway container would build the producers on every stop request.

`JobTransitionService` makes exactly one query to decide eligibility and to supply
content for both messages: `JobEvent.objects.first_running_at(job.id)`. This single
query answers two questions at once, so there is no separate flag to track "did this
job run" and no second query to find out.

### Did the job run: the rule that decides the license fee message

The final usage event (`BillingEvents.build_job_completed_event`) is always built on an
eligible terminal transition, whatever the outcome: even a job cancelled while still
queued gets one, reporting zero usage seconds.

The license fee message (`BillingEvents.build_license_fee`) is only built when the job
is known to have run. The scheduler learns that a job ran by seeing it in `RUNNING`, but a
job can go from `QUEUED` or `PENDING` straight to a terminal status without that ever
happening: it may be extremely fast and end right away, or the scheduler may be slow under
load and miss the window. So the terminal status decides:

- On a transition to `SUCCEEDED`, the job ran by definition (a job cannot succeed without
  having been executed), so the builder is always called, with `job_started_at` being
  `None` if the job was never seen in `RUNNING`.
- On a transition to `FAILED` or `STOPPED`, the builder is only called when
  `first_running_at()` returned a value, that is, the job was seen in `RUNNING` at least
  once before failing or being stopped. Without that event we cannot tell whether the job
  ran and ended inside that short window, or never started at all (the submission failed,
  or it was cancelled while queued). We cannot prove it executed, so it is not charged.

So the only jobs affected are the ones that skipped `RUNNING` and ended in `FAILED` or
`STOPPED`. A job that was seen in `RUNNING` and later failed or was stopped pays the fee as
usual.

Both builders live in `gateway/core/domain/billing_events.py`, alongside the one that
builds the inline usage event, and are pure: `build_job_completed_event` takes `job`,
`job_started_at`, and `job_finished_at` (the just-created `JobEvent`'s own `created`
timestamp), while `build_license_fee` only needs `job` and `job_started_at`. Both
return a dict. Neither one decides whether it should be called or returns `None`; that
decision belongs entirely to `to_succeeded` and `to_stopped_or_failed`. It skips `build_license_fee`
silently when the function has no provider, or its `Program` has itself been deleted
(`SET_NULL`) so whether it had a provider can no longer even be checked, and skips it
with a logged error when the `Program` and its provider are both still there but
`job.function_size` is missing, an anomaly rather than a normal case. `build_license_fee`
itself assumes all of that has already been checked.

Each builder that runs becomes one `Outbox.objects.create(job=job, channel=OutboxChannel.JOB_USAGE
| OutboxChannel.LICENSE_FEE, region=..., payload=message)` call (`region` being the one in the job's instance CRN, or null), inside the same transaction as the status
change.

The message's CloudEvents `id` and `time` are generated when the message is built,
not when it is sent, so a retry after a Kafka outage sends the exact same bytes every
time. The Kafka topic name (the envelope's `type` field) is the one exception: it is
added later, by the sender, at send time, because it is only known once
`KafkaProducers` is instantiated.

## Drain: `OutboxTask`, one drain per channel

`OutboxTask` (`gateway/scheduler/tasks/outbox.py`), wired into the scheduler
loop in `gateway/scheduler/main.py`, holds a `{OutboxChannel: Destination}` registry, where
`Destination` (`gateway/scheduler/tasks/outbox_destination.py`) pairs a sender, a factory of
`CircuitBreaker`s (it keeps one per region), and the `ConfigKey` that holds the time budget in
milliseconds. Those three belong to the destination and not to the channel, so `LICENSE_FEE` and `JOB_USAGE` simply
point at the same `Destination`, whose sender is a `KafkaSender()` today (or `NoOpSender()` when
`EVENT_STREAMS_ENABLED` is false); see "Circuit breaker" below for how that shares the breakers. `OutboxTask`
only builds the destinations and, on every tick, asks the one of each channel to report that channel's gauges and
drain its rows, each channel within its own time budget. A `Destination` is transport-agnostic: it knows only `Outbox`, `Config`, and a sender's `send_batch(messages)` contract (given `PendingMessage(key, payload)` objects, return the keys delivered),
never Kafka or any of its exception types.

For each channel, once a tick, the task first lists the regions that have pending rows (null is one more
region), the one with the oldest row first. Each region has its own breaker: if it is open, the region is
skipped without reading any of its rows. Otherwise the task drains it in successive small batches
(`BATCH_SIZE = 100` rows, a code constant, not a `Config` entry: it bounds a single query, not throughput),
oldest first, until nothing is left pending, the breaker opens, the tick's time budget runs out, or the kill
signal arrives. It pages forward by `(created, pk)` from the last row it saw, so a row that is not delivered
is not retried in a hot loop within one tick; it is picked up again on the next tick.

Each batch goes to the channel's sender in one call, `sender.send_batch([PendingMessage(row.pk, row.payload), ...])`,
with the payloads exactly as stored. The sender knows nothing about `Job`, billing, or licensing and returns the
set of pks it confirmed as delivered. `KafkaSender` produces the whole batch and flushes each producer once,
instead of one flush per row, and marks a pk as delivered only from that message's own delivery callback. The
task deletes exactly the confirmed rows: there is nothing left to re-check, because a row is exactly one
message, and sending it is the only thing it was waiting for.

Any row the sender does not confirm, for whatever reason (`UnroutableRegionError`, a broker
rejection, a flush timeout), stays for the next tick. The breaker records one success if at least one
row of the batch was delivered and one failure only when none was, so isolated bad rows do not open it,
but a whole batch of them does. The time budget is for the healthy path: a region that fails waits
out `KafkaSender`'s own flush timeout (5 s), which spends the budget and ends the tick. The producers
are created with `message.timeout.ms` at 4 s, just under that flush timeout, so a message that cannot
be delivered in time fails inside the flush instead of staying queued and being delivered minutes
later, on top of the copy produced again from its row on the next tick. A message the broker did
write but whose ack came too late is sent again from its row: delivery is at least once. Nothing here deletes a row on failure: a missing region producer is a config gap
(`EVENT_STREAMS_BOOTSTRAP_SERVERS_<REGION>`), and the same row becomes sendable again
once it is added. `KafkaProducers.get`'s other failure mode, a CRN it cannot parse a
region out of at all, is not something this code defends against separately: every
CRN reaching this table was already validated upstream, when the request that owns it
was authorized, so a malformed one here is not expected to occur.

`KafkaSender` (`gateway/core/ibm_cloud/event_streams/kafka_sender.py`) is the sender
behind both billing channels: it adds the Kafka topic name to the payload's `type`
field and publishes it via `KafkaProducers`. The same class also sends the two inline
events (`JobTransitionService` builds via `billing_events.py` and calls
`sender.send(...)` directly, without going through this table): the sender never
builds anything itself and does not know which of the two cases it is in.

## Circuit breaker

Each `Destination` keeps its own circuit breakers: one `CircuitBreaker`
(`gateway/scheduler/tasks/circuit_breaker.py`, built by the `breaker_factory` the destination is given,
`build_kafka_circuit_breaker()` for Kafka, which reads the thresholds from the two `Config` keys below) per region (null included), created the first time that region is seen. An
unreachable region opens only its own breaker and the healthy regions keep draining. Channels
that go through the same `Destination` share its breakers: `LICENSE_FEE` and `JOB_USAGE` both use the Kafka one, so
an outage in a region opens its breaker once for both instead of each channel counting its own failures against
the same underlying connection. A future channel with its own, unrelated sender gets its own `Destination`
instead. While a region's breaker is open, its rows are skipped (not read, not sent, and left for the next tick)
for any channel using that destination, while the other regions are still sent.

- The failure counter is **not** reset between ticks. Failures accumulate across as
  many ticks as it takes to reach the threshold (5 consecutive failures by default),
  whether they land in one tick or are spread across several.
- The only thing that resets the counter to zero is a successful send. Without one in
  between, failures keep adding up indefinitely.
- Once open, it stays open for a fixed pause (60 seconds by default), measured in
  real wall-clock time from the moment it opened, regardless of how many scheduler
  ticks pass meanwhile.
- It closes itself the next time anything asks whether it is open, once that pause
  has elapsed, but half open: the failure counter is left one short of the threshold, so a
  single failure opens it again, while a success clears the streak. A destination that is still
  down therefore costs one probe per pause, not a whole failure streak.
- A region's breaker is checked right before each of its batches is sent, so a failure that
  trips it mid-tick keeps the rest of that region's rows from being sent in the same tick.
- One pass over the pending rows can cost one flush timeout per failing region before the budget
  runs out, and a region that is first in line can then keep the others from being sent until its
  breaker opens.

`OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES` and `OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS` are read lazily through
callables passed into the breaker, so they can change at runtime through `Config`
without recreating the breaker or restarting the process.

## Configuration and observability

Everything except the batch size is a `Config` entry (admin-editable, no redeploy
needed): `scheduler.outbox.kafka.budget_ms` (default 500),
`scheduler.outbox.kafka.breaker_failures` (default 5) and
`scheduler.outbox.kafka.breaker_pause_seconds` (default 60). They apply to all the Kafka
channels together (`LICENSE_FEE` and `JOB_USAGE`), and there is no on/off switch: the Kafka
channels are always active. A future channel that is not Kafka gets its own `Config` keys
and its own `Destination` with its own `budget_key`, without touching these.

Prometheus metrics, all keyed by `channel` (`billing_license_fee`, `billing_job_usage`, or
whatever channel a future PR adds), not by any billing-specific vocabulary:

- `scheduler_outbox_sends_total{channel,outcome}`: one increment per send attempt,
  `outcome` being `"success"` or `"failure"`.
- `scheduler_outbox_pending_rows{channel}` and
  `scheduler_outbox_oldest_pending_age_seconds{channel}`: reported every tick for
  every registered channel, independent of whether that channel's breaker is open.
- `scheduler_outbox_breaker_open{channel}`: 1 while the breaker of at least one region
  of that channel is open. It carries no per-region label, and it is set once every
  channel has been drained, so it reflects a breaker that opened during this very tick, even one that a
  later channel opened, and channels that share a destination always report the same value.

The old `scheduler_outbox_license_fee_irrecoverable_total` counter is gone. The one
case it measured that is still an anomaly today, a licensed function whose
`FunctionSize` has been deleted, is not impossible, but the race window that causes
it shrank from "the whole time a row sat in the outbox" to "the duration of one
database transaction" once messages are built inside the transition rather than at
send time. It is now visible only through a `logger.error(...)` call from
`JobTransitionService._enqueue_license_fee`, not through a metric: `core` cannot import
`SchedulerMetrics` from `scheduler`, and `import-linter` enforces that boundary. A
deleted `Program` (so a function with no known provider) is not part of this: it is
treated as the normal "this job owes no fee" case, silently, with no log line at all.

## Adding a channel

Adding a channel needs no change to `Outbox`'s columns or to `OutboxTask`'s draining
logic. It needs:

1. A new `OutboxChannel` member for it, plus the small `AlterField` migration
   `makemigrations` generates for that (choices= is part of the field's migration-tracked
   state; nothing about the actual data or column changes).
2. A builder that decides when to enqueue a message for that channel and calls
   `Outbox.objects.create(job=job, channel=OutboxChannel.<NAME>, region=..., payload=message)` (`region` is
   the breaker partition, null when the channel has none), wherever in
   the codebase that channel's fact becomes true.
3. A sender class with a `send(payload)` method (and a `send_batch(messages)` override if it can
   confirm many at once; the base class default calls `send` one by one) and its own `ConfigKey`s for the time
   budget and the breaker thresholds, wrapped in one
   `Destination(sender=..., breaker_factory=..., budget_key=..., metrics=..., kill_signal=...)`, registered
   under its own key in `OutboxTask.channels`. A channel that goes to an existing destination just registers that
   same `Destination` under its own key, and shares its sender, breakers and budget `Config` key (each channel still gets its own time window in every tick); one with a new sender builds
   a new `Destination`, with its own breakers.

The `workload` channel, mirroring job state to NTC's Runtime API, is expected to be
exactly this: one more `OutboxChannel` member, one more `Destination`, and one more registry entry,
with its own `Config` keys if its thresholds or kill switch need to differ from the billing
channels'.
