# Fleet Wrapper — COS Upload Specification

## Specification

### 1. Periodic upload to COS

Logs are uploaded to COS every `LOG_FLUSH_INTERVAL_SECONDS` seconds (default: 15).
A final unconditional upload is guaranteed when the job ends, regardless of exit code.
The EXIT trap fires on normal exit, SIGTERM, and SIGINT, so no buffered output is lost.

Uploads are skipped when the local file has not changed size since the last cycle,
avoiding unnecessary COS PUTs when the application is silent.

### 2. Log filtering

Filtering is applied by awk **before** any data reaches the local `/tmp` files.
The size limit and upload logic operate on the already-filtered content.

**Custom job wrapper** (`fleet_custom_job_wrapper.tmpl`):

- All output lines go to the public log.
- `[PUBLIC]` and `[PRIVATE]` prefixes (case-insensitive) are stripped.
- No private log exists.

**Provider job wrapper** (`fleet_provider_job_wrapper.tmpl`):

- **Public log**: only `[PUBLIC]`-tagged lines, prefix stripped.
- **Private log**: `[PRIVATE]`-tagged lines (prefix stripped) + all untagged lines verbatim.
- `[PUBLIC]` lines never appear in the private log.
- Matching is case-insensitive to mirror the Python `re.IGNORECASE` used in
  `core.domain.filter_logs`.

### 3. Exit code propagation

The wrapper captures the application exit code via a sidecar file (`/tmp/app.status`),
because the app runs inside a pipeline (the awk filter) where `$?` would refer to awk,
not the application. The wrapper exits with the real application exit code. The EXIT
trap fires immediately after, performing the final flush before the process terminates.

### 4. Log size limit

COS files are capped at `LOG_SIZE_LIMIT_BYTES` (default: 50 MB, injected by the gateway
from `settings.FUNCTIONS_LOGS_SIZE_LIMIT`). When the limit is exceeded:

- The COS file contains a human-readable truncation header followed by the most recent
  `LOG_SIZE_LIMIT_BYTES` bytes (oldest lines are discarded first).
- The local `/tmp` file is shrunk in-place to the same limit so disk usage stays bounded.
- Both operations share a single `tail -c` read — the tail is written to a temp file
  (`.upload`) and reused for the COS write and the local restore.

When the source is within the limit a plain `cp` is used; no header is added.

### 5. Minimal disk usage

The local `/tmp` files are bounded to approximately `2 × LOG_SIZE_LIMIT_BYTES` at peak:

- The local file itself: up to `LOG_SIZE_LIMIT_BYTES + N` (where N is the bytes written
  during the current interval, typically small).
- The `.upload` temp file: `LOG_SIZE_LIMIT_BYTES` (exists only during the `tail`/`cat`
  operations, removed immediately after).

### 6. Inode preservation during local truncation

Local truncation uses `truncate -s 0` followed by `cat >> file` rather than replacing
the file. This preserves the inode so any open write file descriptor (the awk filter
writing to the log) remains valid after truncation. The brief race window between the
two operations is harmless: a few lines written during that window may appear before the
restored tail, which is acceptable for a log.

---

## Upload flow with file sizes

The following uses `LIMIT = 50 MB` and `INTERVAL = 15 s` as concrete values.

### Phase 1 — growth below the limit

Every 15 seconds, if the local file changed:

```
/tmp/public.log   10 MB   growing normally
/tmp/.upload      —       does not exist

upload_log: cp /tmp/public.log → COS/public.log

COS/public.log    10 MB   exact copy, no header
/tmp/public.log   10 MB   unchanged
```

### Phase 2 — first flush that exceeds the limit

The local file has just crossed 50 MB (e.g. 51 MB at flush time):

```
/tmp/public.log   51 MB   before upload

upload_log (over-limit path):
  step 1  tail -c 50MB /tmp/public.log → /tmp/public.log.upload
          disk peak: 51 MB + 50 MB = 101 MB
  step 2  header + cat .upload → COS/public.log
  step 3  truncate -s 0 /tmp/public.log          (0 MB, same inode)
  step 4  cat .upload >> /tmp/public.log          (50 MB restored)
  step 5  rm /tmp/public.log.upload

COS/public.log    ~50 MB  truncation header + last 50 MB of filtered output
/tmp/public.log   50 MB   shrunk to limit
/tmp/.upload      —       removed
```

### Phase 3 — subsequent flushes after the limit has been reached

The application keeps writing N bytes per interval (e.g. 1 MB):

```
/tmp/public.log   51 MB   50 MB base + 1 MB new lines

upload_log: same as Phase 2
  disk peak: 51 MB + 50 MB = 101 MB during tail+cat

COS/public.log    ~50 MB  header + latest 50 MB (updated every interval)
/tmp/public.log   50 MB   shrunk again
```

The COS file always reflects the **most recent** lines within the limit.
Older lines are permanently discarded once they fall outside the tail window.

### Final flush (job exit)

```
EXIT trap fires → flush_final → upload_log (no pre-computed size)
  same behaviour as Phase 2/3 depending on current file size
  guarantees the very last lines written by the app reach COS
```

For the provider wrapper the same flow applies independently to both
`/tmp/public.log` → `PUBLIC_LOG_PATH` and `/tmp/private.log` → `PRIVATE_LOG_PATH`.
Each log has its own size accounting and is truncated independently.
