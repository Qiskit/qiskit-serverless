{% autoescape off %}# Fleet wrapper for provider jobs — Python implementation.
#
# In Fleets the gateway cannot read logs in real time from the worker, so the
# wrapper that runs inside the container ships the logs to COS itself.  Output
# is written to two local /tmp files (fast disk) and periodically copied to
# the COS-backed mount.  A signal handler + try/finally guarantee a final flush
# so no buffered output is lost when the container terminates.
#
# Provider jobs split output into two logs:
#
#   $PUBLIC_LOG_PATH  (/logs, visible to the job author):
#     Only [PUBLIC]-tagged lines, with the prefix stripped.
#     Equivalent to filter_logs_with_public_tags in core.domain.filter_logs.
#
#   $PRIVATE_LOG_PATH (/provider-logs, visible to the provider):
#     [PRIVATE]-tagged lines (prefix stripped) + all untagged lines verbatim.
#     [PUBLIC] lines are excluded to protect provider IP.
#     Equivalent to filter_logs_with_non_public_tags in core.domain.filter_logs.
#
# Matching is case-insensitive to mirror the Python re.IGNORECASE used in
# core.domain.filter_logs.
import os, shutil, signal, subprocess, sys, threading

# Command to run (injected by the gateway template engine)
app_cmd = {{ app_cmd }}

# How often the logs are uploaded (seconds)
INTERVAL = int(os.environ.get('LOG_FLUSH_INTERVAL_SECONDS', 15))

# Max bytes kept in COS per log before truncating
LIMIT = int(os.environ.get('LOG_SIZE_LIMIT_BYTES', 52428800))

# Local path to COS mounted volume for public logs
COS_PUBLIC_PATH = os.environ['PUBLIC_LOG_PATH']

# Local path to COS mounted volume for private logs
COS_PRIVATE_PATH = os.environ['PRIVATE_LOG_PATH']

# Fast local buffer for public lines; periodically synced to COS
LOCAL_PUBLIC_LOG = '/tmp/public.log'

# Fast local buffer for private lines; periodically synced to COS
LOCAL_PRIVATE_LOG = '/tmp/private.log'

# Log prefix tags for line filtering (case-insensitive)
PUBLIC_TAG = '[PUBLIC]'
PRIVATE_TAG = '[PRIVATE]'

# Truncation header written to COS when the log exceeds LIMIT
TRUNCATION_HEADER = (
    '[Logs exceeded maximum allowed size ({} MB). Logs have been '
    'truncated, discarding the oldest entries first.]\n'
).format(LIMIT // 1048576).encode()


class JobWrapper:
    def __init__(self):
        # Signals the uploader thread to stop
        self.stop = threading.Event()
        # User process with the real function, source of logs and exit code
        self.user_process = None
        # Background thread that periodically copies logs to COS
        self.uploader_thread = None
        # Exit code set by signal handler; None means normal termination
        self.exit_code = None

    def file_size(self, path):
        try:
            return os.path.getsize(path)
        except OSError:
            return -1

    # Read the last bytes from the file (seek from end of file)
    def tail(self, path, size):
        with open(path, 'rb') as f:
            f.seek(-size, 2)  # 2 = start from the end of file
            return f.read()

    # Shrink the file in-place, preserving the inode so the line-reader loop can keep writing to it
    def truncate_file(self, path, content):
        with open(path, 'r+b') as f:
            f.truncate(0)
            f.seek(0)
            f.write(content)

    # Copies temporal_log_path to cos_path, capping output at LIMIT bytes
    # and shrinking temporal_log_path in-place when the limit is exceeded —
    # reading the tail only once for both operations.
    #
    # When within the limit a plain copy is used.  When over, the last
    # LIMIT bytes are saved to a variable, written to cos_path with a
    # truncation header, then restored to temporal_log_path via
    # truncate+seek+write so the inode is preserved and any open write fd
    # (the line-reader loop) remains valid after truncation.
    def upload_log(self, temporal_log_path, cos_path):
        size = self.file_size(temporal_log_path)
        if size < 0:
            return
        if size >= LIMIT:
            try:
                log_tail = self.tail(temporal_log_path, LIMIT)
                # Write (upload to COS) the truncation header + the log tail
                with open(cos_path, 'wb') as f:
                    f.write(TRUNCATION_HEADER)
                    f.write(log_tail)
                self.truncate_file(temporal_log_path, log_tail)
            except OSError:
                pass
        else:
            try:
                shutil.copyfile(temporal_log_path, cos_path)
            except OSError:
                pass

    # Periodically copies both local logs to COS, skipping no-op PUTs when the
    # app is silent or no line has matched a given filter.  Runs as a daemon thread.
    def run_uploader_thread(self):
        last_public_size = last_private_size = -1
        while not self.stop.wait(INTERVAL):
            current_public_size = self.file_size(LOCAL_PUBLIC_LOG)
            if current_public_size != last_public_size:
                self.upload_log(LOCAL_PUBLIC_LOG, COS_PUBLIC_PATH)
                last_public_size = self.file_size(LOCAL_PUBLIC_LOG)
            current_private_size = self.file_size(LOCAL_PRIVATE_LOG)
            if current_private_size != last_private_size:
                self.upload_log(LOCAL_PRIVATE_LOG, COS_PRIVATE_PATH)
                last_private_size = self.file_size(LOCAL_PRIVATE_LOG)

    # Stops the uploader thread (waits for any in-progress upload to finish),
    # then performs one final unconditional upload of both logs.
    def flush(self):
        self.stop.set()
        if self.uploader_thread is not None:
            self.uploader_thread.join(timeout=5)
            if self.uploader_thread.is_alive():
                self.uploader_thread.join()
        self.upload_log(LOCAL_PUBLIC_LOG,  COS_PUBLIC_PATH)
        self.upload_log(LOCAL_PRIVATE_LOG, COS_PRIVATE_PATH)

    def on_signal(self, sig, _frame):
        if self.user_process is not None:
            self.user_process.terminate()
        # POSIX convention: exit code for signal-terminated processes is 128 + signal number
        self.exit_code = 128 + sig

    # Routes a log line to (pub, stripped_line) or (priv, stripped_or_verbatim_line).
    # [PUBLIC] lines go to pub; [PRIVATE] and untagged lines go to priv.
    def clean_line(self, line, pub, priv):
        if line[:len(PUBLIC_TAG)].upper() == PUBLIC_TAG:
            return pub, line[len(PUBLIC_TAG) + 1:]
        if line[:len(PRIVATE_TAG)].upper() == PRIVATE_TAG:
            return priv, line[len(PRIVATE_TAG) + 1:]
        return priv, line

    def run(self):
        # daemon=True: thread will die with the current process
        self.uploader_thread = threading.Thread(target=self.run_uploader_thread, daemon=True)
        self.uploader_thread.start()

        # Execute the real user function as a new process, so we can capture the logs. bufsize=1: line-buffered
        self.user_process = subprocess.Popen(
            app_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        signal.signal(signal.SIGTERM, self.on_signal)  # container shutdown / kill
        signal.signal(signal.SIGINT, self.on_signal)   # Ctrl+C
        try:
            # Listen to changes in the local temporal log files
            with open(LOCAL_PUBLIC_LOG,  'a', buffering=1) as pub, \
                 open(LOCAL_PRIVATE_LOG, 'a', buffering=1) as priv:
                # Process changes line by line
                for line in self.user_process.stdout:
                    out, cleaned = self.clean_line(line, pub, priv)
                    # out could be private logs or public, based on the prefix (or the absence of)
                    # [PRIVATE] or no prefix, return priv (removing the prefix)
                    # [PUBLIC] returns pub (removing the prefix)
                    out.write(cleaned)
                    out.flush()
            code = self.user_process.wait()
        finally:
            self.flush()

        sys.exit(self.exit_code if self.exit_code is not None else code)


JobWrapper().run()
{% endautoescape %}
