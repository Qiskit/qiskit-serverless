# Performance test

A load driver that acts like many users of the gateway at the same time. Each user follows the tutorial notebook (`docs/function_features/basic/01_custom_upload_run.ipynb`) with the real `ServerlessClient`: it signs in, uploads a custom function, runs it, checks the job status until the job ends, and gets the result. The function is the SQD IEF-PCM chemistry function, so every job does real work. The driver records every HTTP call, reads the job events, the pod and scheduler metrics from Sysdig and the submit times from Cloud Logs, and writes a report.

## Run it

From `tests/`:

```bash
export GATEWAY_HOST=<the gateway under test, for example https://...>
export GATEWAY_TOKEN=<API key of the test service ID>
export GATEWAY_INSTANCE=<CRN of the test instance>
export IBM_CLOUD_API_KEY=<IBM Cloud API key that can read the monitoring, the logs and the Code Engine project>

# optional: each group turns on one part of the report. Without it the run still works.
export PERF_SYSDIG_REGION=<region> PERF_SYSDIG_INSTANCE=<instance id> PERF_SYSDIG_CLUSTER=<kube_cluster_name>
export PERF_LOGS_REGION=<region> PERF_LOGS_INSTANCE=<IBM Cloud Logs instance id>   # the submit split
export PERF_CE_REGION=<region> PERF_CE_PROJECT=<Code Engine project id>            # delete the fleets

tox -e performance -- run --dry-run                      # print the plan and check the limits
tox -e performance -- run --only burst_10                 # run one scenario, then clean up its jobs and fleets
tox -e performance -- run --only burst_10 --keep          # leave the jobs and fleets for inspection
tox -e performance -- report runs/<run id>               # build report.txt again
tox -e performance -- compare runs/<a> runs/<b> runs/<c>  # the main numbers of several runs, side by side
tox -e performance -- export <results clone> runs/<run id> # write a run into the results repo, for its dashboard
tox -e performance -- export <results clone> --new         # write every finished run not yet in the results repo
tox -e performance -- run --results <results clone>        # export each scenario into the results repo when it ends
tox -e performance -- publish <results clone>              # export the new runs, commit them and push to every remote
tox -e performance -- publish <results clone> --dry-run    # show what publish would do, change nothing
tox -e performance -- cleanup runs/<run id>              # clean up a run that used --keep or was stopped
```

A run takes as long as its slowest job. On macOS the driver keeps the machine awake with `caffeinate` until it ends. A machine that sleeps pauses the driver, and the job times are wrong. The driver health section shows a pause like that.

The driver prints a progress line when the counts change, and at least once a minute. The last line of each scenario starts with `result`, for example `result burst_50: 50 DONE, 0 failed, 5 failed status checks, report runs/.../report.txt`.

Without tox, from `tests/performance/`: `pip install -r requirements.txt -e ../../client`, then `python -m perf <command>`.

## Files

| File | What it holds |
|---|---|
| `scenarios.yaml` | the functions, their sizes, and the scenarios, run in order. Comment one out to skip it. |
| `metrics.yaml` | the Sysdig PromQL queries, one entry per metric. Add one by adding a name and a query. |
| `functions/sqd_pcm/` | the SQD IEF-PCM chemistry function from `qiskit-function-templates`, at 933180d87. With `use_fake_backend: true` it runs with a fake backend and saved counts, so it needs no QPU. |

## The scenarios

Each scenario sends its users through one rate limiter, like the `qps` and `burst` of the Kubernetes client-go rate limiter that kube-burner also uses:

- `burst`: how many users can submit at the same moment.
- `qps`: how many more users can submit each second after that.

| Example | What happens |
|---|---|
| `users: 10, qps: 10, burst: 10` | all 10 submit at the same moment |
| `users: 200, qps: 2, burst: 20` | 20 submit at once, then 2 per second, so the last one submits at 90 s |

No one waits for the jobs of the others, so with long jobs the jobs pile up and overlap, like QDC users who arrive a few seconds apart. `--dry-run` prints when the last user submits.

Between two scenarios the driver waits `cooldown_seconds` (default 300), then until the Code Engine project has room for the next scenario's fleets. A fleet that is being deleted still counts against the 1000 cap. A scenario with `wait_for_room: false` starts at once instead, for a test that fills the project on purpose with `--keep`. Each run picks its size with `function_size`, from the `sizes` of the function, for example `S` is `8x32`. Code Engine performance is not what we test, so use the smallest size the function needs.

**The function's arguments** are in `sqd_arguments`, the input of the template's own unit test: a small water molecule, 2 SQD iterations, and 2 batches. The chemistry takes about 10 s. Most of a job's time is Code Engine starting its fleet.

| `use_fake_backend` | What runs | `backend_name` |
|---|---|---|
| `true` (default) | a fake backend and saved counts, no QPU | ignored |
| `false` | a real QPU through Qiskit Runtime | required: a device name your instance can use |

For a real QPU the function needs no other setting. The gateway passes the user's credentials into the job as `QISKIT_IBM_TOKEN`, `QISKIT_IBM_CHANNEL` and `QISKIT_IBM_INSTANCE`, the same as `GATEWAY_TOKEN` and `GATEWAY_INSTANCE`, and `get_runtime_service()` reads them. Each user then sends one QPU job, so the QPU queue time is part of the job time. Use it to check that it works, not for a load test.

**What each user does,** like the tutorial notebook:

1. The driver starts one thread per user.
2. The thread builds its own `ServerlessClient`, which checks the credentials with `GET /programs/`.
3. It uploads its own copy of the function, as `<title>-u<n>`, for example `perf-sqd-pcm-u003`. The title is the same in every run, so the next run uploads over it instead of adding a new function.
4. It waits until every user has uploaded, so the upload time does not slow the submits.
5. It takes a token from the rate limiter, then calls `run(function_size=...)`.
6. It writes its job id to `job_ids.jsonl` as soon as `run()` returns, so `cleanup` can find the job even if the driver is killed.
7. It checks its job status every `poll_seconds` until the job is `DONE`, `ERROR` or `CANCELED`. With `poll: backoff` in a scenario, it waits like `Job.wait_for_final_state()` instead: 1, 2, 4, 8, 16 and 32 s, then every 60 s, starting again from 1 s when the status changes. That is how a real SDK user polls.
8. It gets the result with `job.result(wait=False)`. It does not wait, because the job already ended.
9. When every job has ended, the driver reads the status events and the log of each job, the Sysdig metrics from the start of the run to one scrape after its end, and the scheduler submit lines from Cloud Logs.
10. It writes `report.txt`, then cleans up the jobs and their fleets. With `--results`, it then exports the run into the results repo.

```
user thread                   staging gateway              Code Engine
-----------                   ---------------              -----------
sign in           --------->
upload own copy   --------->  (sizes S, M, L)
wait until every user has uploaded
take a token from the rate limiter
run (size S)      --------->  job QUEUED
                              scheduler submits --------->  fleet starts
status            --------->  every poll_seconds, until DONE
                                            <-------------  job DONE
result            --------->
after the last job ends: events, logs, Sysdig, report.txt, cleanup
```

The report gives these times for each job:

| Time | From | To |
|---|---|---|
| `QUEUED` | the `QUEUED` event | the `PENDING` event, when the scheduler submitted the job |
| `PENDING` | the `PENDING` event | the `RUNNING` event |
| real start | the `PENDING` event | the `perf-start` line the function prints, when it really started in Code Engine |
| submit | the scheduler starts the submit | the scheduler log line `Execute job (N s)`, split into COS upload, prepare, create fleet and save |
| all started | the first `QUEUED` event of the run | the last real start of the run |

## Prepare the system

Every user signs in with the same `GATEWAY_TOKEN`, so for the gateway they are one user. And no user waits for the jobs of the others, so with long jobs every job of the run can exist at the same time. So a run with more than 50 users needs the per-user limit raised first. `--dry-run` warns about it.

| What | For the test | Where | How it reaches staging |
|---|---|---|---|
| Jobs per user, queued or running (default 50) | above the number of users | the Config `gateway.limits.active_jobs_per_user` | the backoffice |
| Fleets jobs started per scheduler tick (default 5) | the number of users, so one tick starts a whole step | the Config `scheduler.fleets.jobs_per_tick` | the backoffice |
| Gateway and scheduler CPU and memory | like production, so the results carry over. | `gateway.resources` and `gateway.scheduler.resources` in the internal `values-non-prod.yaml` | an internal values PR, then a staging release |
| Compute size | the smallest the function needs, for example `S`, `8x32` | `sizes` and `function_size` in `scenarios.yaml`. The profile must be registered in the gateway. | nothing, the driver sends it |
| Code Engine room | room for every fleet of the run. A project holds at most 1000 fleets, and a fleet that is being deleted still counts | the Code Engine project | the driver waits for room before each scenario, and deletes each fleet when its job ends |

**Before each run:**
- Check that the profiles in `sizes` are registered in the gateway. The upload fails otherwise.
- Each user uploads its own copy, and a custom function lands in the default Code Engine project. So the jobs run in that project.
- Set `PERF_SYSDIG_*` to the monitoring instance of the cluster under test, not of another environment.

## Output

Each scenario writes `runs/<UTC time>-<scenario>/`:

| File | What it holds |
|---|---|
| `calls.jsonl` | one line per HTTP call: method, path, status, time seen by the client, and the server time from `x-envoy-upstream-service-time` |
| `users.jsonl` | one line per user: the job id, the statuses it saw, and the error, if any |
| `job_ids.jsonl` | each job id as soon as `run()` returns, so `cleanup` works after a killed run |
| `jobs.jsonl` | the status events of each job, and the start time its function printed |
| `submits.jsonl` | the scheduler submit time of each job from Cloud Logs, split into its parts |
| `sysdig.json` | every query of `metrics.yaml` over the run window, and the Sysdig clock offset |
| `health.jsonl` | the driver itself, once a second: its CPU as a share of one core, and how late it woke up |
| `meta.json`, `scenarios.yaml`, `metrics.yaml` | what ran |
| `report.txt` | the summary of the run, with its outliers: the calls and jobs above Q3 + 1.5 IQR, and the 5 worst of each |

## After a run

By default, a run cleans up after its report: it cancels the jobs that are still active, waits for them to end, and deletes their fleets. It deletes them with the Code Engine REST API, signed in with `IBM_CLOUD_API_KEY`, in the project of `code_engine` in `scenarios.yaml`. It needs no `ibmcloud` CLI. With `--keep`, it leaves everything for inspection, and `cleanup runs/<run id>` does it later.

The uploaded functions stay, because the gateway has no endpoint to delete one. Each user always uploads under the same title, so the next run overwrites them.
