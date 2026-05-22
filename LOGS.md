# Job logs

This document describes the new logging system for jobs, including log types, filtering rules, API endpoints and client.

### Job types

Based on the `job.program.provider` field, from the logs point of view, we consider jobs of two types:
1. User jobs (no `program.provider`): Users develope and run their own functions.
2. Provider jobs (`program.provider` exists): Providers develop functions that users can execute.

### Log prefixes

During the function execution, the code could use `get_logger()` or `get_provider_logger()` from the serverless-client sdk to print logs. At any time other text can be printed to the console (through a regular `print()` or using other loggers).

| Logger | Prefix added |
|--------|--------------|
| `get_logger()` | `[PUBLIC]` |
| `get_provider_logger()` | `[PRIVATE]` |
| `print()` or other loggers | No prefix |

## How are the logs obtained

User gets the logs using the `logs()` and `provider_logs()` methods from the client (they will use `/logs` and `/provider-logs` respectively). The flow depends on the runtime backend (Ray or Fleets) and on whether the job is still running.

### Ray jobs

- During execution: logs are obtained from Ray's console while the job is running, and the filter functions are applied at read time.
- After execution: logs are obtained from COS. The scheduler checks if the job has finished in the `update_job_statuses`
  step and uploads logs to COS, already filtered:
  - In user jobs: one file with all logs (prefixes removed).
  - In provider jobs: two files (public and private) with different filtering rules:
    - Provider logs: all logs but the lines with the `[PUBLIC]` prefix.
    - Public logs: the lines with the `[PUBLIC]` prefix only.

### Fleet jobs

In Fleets the gateway cannot read the worker output in real time, so there is no "from Ray" path. Instead, the wrapper script that runs inside the container is responsible for shipping the logs to COS itself, both during the run (for near real-time visibility) and at the end.

- The wrapper writes to local files in `/tmp` (fast disk) and copies them to the COS-backed mount every `LOG_FLUSH_INTERVAL_SECONDS` (default 15s), skipping the upload when the file has not changed since the previous one.
- An `EXIT`/`TERM`/`INT` trap performs an unconditional final copy when the application terminates, so the last lines reach COS even on cancel or scale-down.
- The files in COS are already filtered, so the endpoints can serve them as-is without re-applying any filter. The public log is always present (it is the file served by `/logs` to the job's author); the private log is the addition that provider jobs need on top, served by `/provider-logs`:
  - Custom (user) jobs: a single file under `PUBLIC_LOG_PATH` equivalent to `remove_prefix_tags_in_logs` applied to the raw output.
  - Provider jobs: two files. `PUBLIC_LOG_PATH` equivalent to `filter_logs_with_public_tags` and `PRIVATE_LOG_PATH` equivalent to `filter_logs_with_non_public_tags`.
- Prefix matching in the wrapper is case-insensitive, mirroring the `re.IGNORECASE` used by the Python filter functions.
- Freshness of the COS file is bounded by `LOG_FLUSH_INTERVAL_SECONDS`; the endpoint always reads from COS for Fleet jobs.

## Legacy logs

Before uploading logs to COS, the logs were saved in the jobs table. The original code before this feature was simple:
- There was only one endpoint to query all logs (logs() calling to `/jobs`)
- The endpoint returned the job.logs from the db.

## API Endpoints

There are two endpoints to query logs: `/logs` and `/provider-logs`. First one is for users only and second one is for providers only.

The logs could be fetched 1) from COS in completed jobs or 2) from Ray in running jobs. So the tricky part is that the file from COS should already be transformed, but if the logs are downloaded from Ray, the transformation has to be done at that moment.
Old jobs before this feature don't have the COS file, so as a fallback, the endpoint returns the logs from the database.

### Endpoint: `/logs` for public logs

Called via `job.logs()` from the client. The `request.user` must match the job author (`job.author` actually).

- If it's a user job: Returns all logs without filtering
- If it's a provider job: Returns filtered logs showing only `[PUBLIC]` content (`[PRIVATE]` and unprefixed logs disappear)

In both cases, the prefixes are removed for cleaner output.

### Endpoint: `/provider-logs` for private logs

Called via `job.provider_logs()` from the client only by the provider in provider jobs.

So, if it's an user job:
- Returns a permission error (job must be a provider job)

If it's a provider job:
- `request.user` must be the job's provider (author doesn't matter)
- Returns filtered logs containing `[PRIVATE]`, and 3rd party content (`[PUBLIC]` content and prefixes are removed)


These are the behavior table for the endpoints. The `1-COS File` and `2-Ray` columns describe the Ray flow, where filtering is applied at read time. For Fleet jobs the COS file is pre-filtered by the in-container wrapper (see "Fleet jobs" above), so the endpoint streams it without applying any extra filter.

| Job Type | Caller | Endpoint | 1-COS File | 2-Ray | 3-Db (legacy) |
|----------|--------|----------|------------|-------|---------------|
| User | Author | `/logs` | `remove_prefix_tags_in_logs` | `remove_prefix_tags_in_logs` | job.logs |
| User | Any | `/provider-logs` | Error (not provider) | Error (not provider) | - |
| Provider | Author | `/logs` | `filter_logs_with_public_tags` | `filter_logs_with_public_tags` | "No logs available." |
| Provider | Author | `/provider-logs` | Error (not provider) | Error (not provider) | - |
| Provider | Provider | `/logs` | Permission error | Permission error | "No logs available." |
| Provider | Provider | `/provider-logs` | `filter_logs_with_non_public_tags` | `filter_logs_with_non_public_tags` | job.logs |
| Any | Other | `/logs` `/provider-logs` | Permission error | Permission error | - |

Filters description:
- `remove_prefix_tags_in_logs`: Removes `[PUBLIC]` and `[PRIVATE]` prefixes, keeps all lines
- `filter_logs_with_public_tags`: Keeps only `[PUBLIC]` lines, removes the prefix
- `filter_logs_with_non_public_tags`:  Removes `[PUBLIC]` lines and `[PRIVATE]` prefixes

## Design decisions

- "3rd party logs"
Unprefixed logs (regular `print()` statements or other loggers from the user or 3rd party libraries) that appear in the console are treated as unclassified content.
In provider jobs, they are hidden from users to protect intellectual property.

- No validation of `get_provider_logger()` in user Jobs
If a user uses `get_provider_logger()` by mistake in a user job, it will work as usual (adding the `[PRIVATE]` prefix). Since user jobs show all logs unfiltered, the user will see the content (with the prefix removed).

