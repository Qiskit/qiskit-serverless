# Fleet Wrapper — COS Upload Specification

## Relevant files

| File | Role |
|------|------|
| `gateway/templates/fleet_custom_job_wrapper.py` | Python wrapper for custom (user) jobs — single public log |
| `gateway/templates/fleet_provider_job_wrapper.py` | Python wrapper for provider jobs — public + private logs |
| `gateway/core/ibm_cloud/code_engine/fleets/utils.py` | Renders the wrapper template and returns `["python3", "-c", script]`; injects `LOG_SIZE_LIMIT_BYTES` and `LOG_FLUSH_INTERVAL_SECONDS` as env vars via `build_run_env_variables` |
| `gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_fleet_template.py` | Tests (Docker) for filtering, truncation, exit-code propagation, periodic flush |
| `gateway/tests/core/services/ibm_cloud/code_engine/fleets/test_fleet_handler.py` | Unit tests for the fleet handler |

---

## Specification

### 1. Periodic upload to COS

Logs are uploaded to COS every `LOG_FLUSH_INTERVAL_SECONDS` seconds (default: 15).
A final unconditional upload is guaranteed when the job ends, regardless of exit code.
The `try/finally` block and SIGTERM/SIGINT signal handlers guarantee a final flush
so no buffered output is lost when the container terminates.

Uploads are skipped when the local file has not changed size since the last cycle,
avoiding unnecessary COS PUTs when the application is silent.

### 2. Log filtering

Filtering is applied in Python as each line is read from the subprocess stdout,
before any data reaches the local `/tmp` files.
The size limit and upload logic operate on the already-filtered content.

**Custom job wrapper** (`fleet_custom_job_wrapper.py`):

- All output lines go to the public log.
- `[PUBLIC]` and `[PRIVATE]` prefixes (case-insensitive) are stripped.
- No private log exists.

**Provider job wrapper** (`fleet_provider_job_wrapper.py`):

- **Public log**: only `[PUBLIC]`-tagged lines, prefix stripped.
- **Private log**: `[PRIVATE]`-tagged lines (prefix stripped) + all untagged lines verbatim.
- `[PUBLIC]` lines never appear in the private log.
- Matching is case-insensitive to mirror the Python `re.IGNORECASE` used in
  `core.domain.filter_logs`.

### 3. Exit code propagation

The wrapper launches the application via `subprocess.Popen` and captures its exit code
with `proc.wait()`. The wrapper exits with the real application exit code, or `128 +
signal_number` when terminated by a signal. The SIGTERM/SIGINT handler only terminates
the child process and records the exit code; the `try/finally` block performs a single
final flush before the process exits, regardless of whether the application exits
normally or the container receives a signal.

### 4. Log size limit

COS files are capped at `LOG_SIZE_LIMIT_BYTES` (default: 50 MB, injected by the gateway
from `settings.FUNCTIONS_LOGS_SIZE_LIMIT`). When the limit is exceeded:

- The COS file contains this human-readable truncation header followed by the most recent
  `LOG_SIZE_LIMIT_BYTES` bytes (oldest lines are discarded first):
  `[Logs exceeded maximum allowed size (%s bytes). Logs have been truncated, discarding the oldest entries first.]`
- The local `/tmp` file is shrunk in-place to the same limit so disk usage stays bounded.
- Both operations share a single `f.seek(-LIMIT, 2); f.read()` — the tail bytes are held
  in memory and reused for the COS write and the local restore, then freed by the GC.

When the source is within the limit a plain `shutil.copy` is used; no header is added.

### 5. Memory usage

`/tmp` inside containers is backed by `tmpfs` — it lives in RAM, not on disk.
All `/tmp` files therefore count as RAM, not disk.

The tail buffer read during an over-limit upload is a Python `bytes` object on the
heap — also RAM. Both contributions must be counted together.

**Custom job wrapper** (single log) — peak RAM during an over-limit upload:

- `/tmp/public.log` in tmpfs: up to `LOG_SIZE_LIMIT_BYTES + N`
- `tail` bytes object on heap: `LOG_SIZE_LIMIT_BYTES` (freed after upload)
- **Total peak: ~2 × LOG_SIZE_LIMIT_BYTES** (≈ 100 MB at the default 50 MB limit)

**Provider job wrapper** (two logs) — same peak because uploads are sequential:

- `/tmp/public.log` + `/tmp/private.log` in tmpfs: up to `2 × LOG_SIZE_LIMIT_BYTES + N + M`
- One `tail` bytes object on heap at a time: `LOG_SIZE_LIMIT_BYTES`
- **Total peak: ~3 × LOG_SIZE_LIMIT_BYTES** (≈ 150 MB at the default 50 MB limit)

### 6. Inode preservation during local truncation

Local truncation opens the file with `open(temporal_log_path, 'r+b')` (no replace), then calls
`f.truncate(0)` followed by `f.seek(0)` and `f.write(tail)` rather than replacing
the file. This preserves the inode so any open write file descriptor (the line-reader
loop appending to the log) remains valid after truncation. The brief race window between
`truncate(0)` and `write(tail)` is harmless: a few lines written during that window may
appear before the restored tail, which is acceptable for a log.

---

## Upload flow with file sizes

The following uses `LIMIT = 50 MB` and `INTERVAL = 15 s` as concrete values.

### Phase 1 — growth below the limit

Every 15 seconds, if the local file changed:

```
/tmp/public.log   10 MB   growing normally (tmpfs = RAM)

upload_log: shutil.copy /tmp/public.log → s3://bucket/public.log

s3://bucket/public.log    10 MB   exact copy, no header
/tmp/public.log           10 MB   unchanged
heap                       —      no tail buffer allocated
RAM peak: 10 MB (just the tmpfs file)
```

### Phase 2 — first flush that exceeds the limit

The local file has just crossed 50 MB (e.g. 51 MB at flush time):

```
/tmp/public.log   51 MB   before upload (tmpfs = RAM)

upload_log (over-limit path):
  step 1  f.seek(-50MB, 2); tail = f.read()    → 50 MB on heap
          RAM: 51 MB (tmpfs) + 50 MB (heap) = 101 MB  ← peak
  step 2  open(dst, 'wb'); write header + tail  → s3://bucket/public.log
  step 3  open(src, 'r+b'); f.truncate(0)       (tmpfs: 0 MB, same inode)
          f.seek(0); f.write(tail)              (tmpfs: 50 MB restored)
  step 4  tail goes out of scope → GC frees heap

s3://bucket/public.log    ~50 MB  truncation header + last 50 MB of filtered output
/tmp/public.log            50 MB  shrunk to limit (tmpfs)
heap                        —     tail buffer freed
RAM after: 50 MB
```

### Phase 3 — subsequent flushes after the limit has been reached

The application keeps writing N bytes per interval (e.g. 1 MB):

```
/tmp/public.log   51 MB   50 MB base + 1 MB new lines (tmpfs)

upload_log: same as Phase 2
  RAM peak: 51 MB (tmpfs) + 50 MB (heap) = 101 MB during steps 1–3

s3://bucket/public.log    ~50 MB  header + latest 50 MB (updated every interval)
/tmp/public.log            50 MB  shrunk again (tmpfs)
```

The COS file always reflects the **most recent** lines within the limit.
Older lines are permanently discarded once they fall outside the tail window.

### Final flush (job exit)

```
try/finally block fires → flush() → upload_log
  same behaviour as Phase 2/3 depending on current file size
  guarantees the very last lines written by the app reach COS
```

For the provider wrapper the same flow applies independently to both
`/tmp/public.log` → `PUBLIC_LOG_PATH` and `/tmp/private.log` → `PRIVATE_LOG_PATH`.
Each log has its own size accounting and is truncated independently.

---

## Python wrapper vs Bash wrapper

### Memory

Because `/tmp` is `tmpfs` (RAM-backed), both implementations have the same
**~2× LIMIT** peak for the file operations themselves — the bash version stored
the tail in a `.upload` tmpfs file; the Python version stores it in a heap
`bytes` object. Neither is cheaper in total RAM for the upload step.

The meaningful difference is **process overhead**:

| | Wrapper process RAM | Extra processes |
|---|---|---|
| **Bash** | `sh` ~2 MB | `awk` ~2 MB + uploader subshell ~2 MB |
| **Python** | `python3` interpreter ~25–40 MB | none |

Python adds ~20–35 MB of interpreter overhead compared to bash, but eliminates
the awk and subshell processes. For containers running Qiskit workloads (which
require several GB for quantum computations), this difference is negligible.

There is also a second Python process — the user's app runs as a `subprocess.Popen`
child — so two Python interpreters coexist during job execution. This was also the
case with bash (the app was always `python main.py`); the wrapper language doesn't
change that.

### Pros of the Python implementation

- **Simpler provider wrapper**: no FIFO (`mkfifo`), no background `awk` process,
  no `LOGGER_PID`, no `wait "$LOGGER_PID"`. The output split is a plain `if/elif`
  in a line-reading loop.
- **No external tool dependencies**: no `awk`, `stat`, `truncate`, `mkfifo`, `tail`
  required in the container image. Only Python's standard library is needed.
- **Correct by construction**: `proc.wait()` returns the exit code directly;
  no sidecar file, no shell pipeline `$?` ambiguity.
- **Safer subprocess call**: `subprocess.Popen(list, shell=False)` — no shell
  injection risk.
- **Thread-based uploader**: cleaner lifecycle than a background subshell; the
  `threading.Event` stop mechanism waits for any in-progress upload to finish
  before the final flush, eliminating the double-flush on SIGTERM.
- **Maintainability**: Python exceptions, traceback, `OSError` handling vs silent
  `2>/dev/null` failures in shell.

### Cons of the Python implementation

- **Interpreter overhead**: ~25–40 MB RAM for the wrapper's `python3` process,
  vs ~2 MB for `sh`. Negligible for Qiskit workloads but non-zero.
- **Startup latency**: Python interpreter initialisation adds ~50–100 ms before
  the first line of the wrapper runs. Negligible for jobs that run minutes.
- **`python3` required**: the container image must have `python3` available.
  Production images are guaranteed to have it (they run Python functions).
  Test images must use `python:3-alpine` instead of `alpine:3`.
