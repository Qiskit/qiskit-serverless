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

User gets the logs using the logs() and provider_logs() methods from the client (they will use /logs and /provider-logs respectively). Based on the log state, the endpoints will:

- During execution: logs are obtained from Ray's console while the job is running.
- After execution: logs are obtained from COS (Cloud Object Storage).

To download from COS, the logs must be uploaded there first. So, the scheduler will check if the job has finished in the `free_resources` step, and uploads logs to COS:
- In user jobs: one file with all logs (removing the prefixes)
- In provider jobs: two files (public and private) with different filtering rules

## Legacy logs

Before uploading logs to COS, the logs were saved in the jobs table. The original code before this feature was simple:
- There was only one endpoint to query all logs (logs() calling to `/jobs`)
- The endpoint returned the job.logs from the db.

## API Endpoints

There are two endpoints to query logs: `/logs` and `/provider-logs`. Both can be called by users or providers and can query user jobs or provider jobs.

The logs could be fetched 1) from COS in completed jobs or 2) from Ray in running jobs. So the tricky part is that the file from COS should already be transformed, but if the logs are downloaded from Ray, the transformation has to be done at that moment.
Old jobs before this feature don't have the COS file, so as a fallback, the endpoint returns the logs from the database.

### Endpoint: `/logs` for public logs

Called via `job.logs()` from the client.

If it's a user job:
1. `request.user` must match the job author (`job.author`actually)
2. Returns all logs without filtering (prefixes removed for cleaner output)

If it's a provider job:
1. `request.user` must match the job author OR be the job's provider
2. Returns filtered logs showing only `[PUBLIC]` content (`[PRIVATE]` and unprefixed logs disappear), removing prefixes from returned logs

### Endpoint: `/provider-logs` for private logs

Called via `job.provider_logs()` from the client only by the provider in provider jobs.

So, if it's a user job:
- Returns a permission error (job must be a provider job)

If it's a provider job:
- `request.user` must be the job's provider (author doesn't matter)
- Returns unfiltered raw logs containing `[PRIVATE]`, `[PUBLIC]`, and 3rd party content (prefixes are maintained)


These are the behavior table for the endpoints. 

| Job Type | Caller | Endpoint | 1-COS File | 2-Ray                                | 3-Db (legacy)       |
|----------|--------|----------|------------|--------------------------------------|---------------------|
| User | Author | `/logs` | Public     | All, but prefixes removed            | job.logs            |
| User | Other | `/logs` |            | Permission error                     | "No available logs" |
| User | Any | `/provider-logs` |            | Error (not provider)                 |                     |
| Provider | Author | `/logs` | Public     | `[PUBLIC]` only, removing the prefix | job.logs            |
| Provider | Author | `/provider-logs` |            | Error (not provider)                 |                     |
| Provider | Provider | `/logs` | Public     | `[PUBLIC]` only, removing the prefix | job.logs                    |
| Provider | Provider | `/provider-logs` | Private    | No filter                            | job.logs                    |

## Design decisions

- "3rd party logs"
Unprefixed logs (regular `print()` statements or other loggers from the user or 3rd party libreries) that appear in the console are treated as unclassified content.
In provider jobs, they are hidden from users to protect intellectual property.

- No validation of `get_provider_logger()` in user Jobs
If a user uses `get_provider_logger()` by mistake in a user job, it will work as usual (adding the `[PRIVATE]` prefix). Since user jobs show all logs unfiltered, the user will see the content (with the prefix removed).

- Provider access to `/logs`
Providers can call `/logs` to see how the output appears from the user's perspective, which is useful for debugging.


