{% autoescape off %}# Fleet wrapper for custom (user) jobs — Python implementation.
#
# In Fleets the gateway cannot read logs in real time from the worker, so the
# wrapper that runs inside the container ships the logs to COS itself.  Output
# is written to a local /tmp file (fast disk) and periodically copied to the
# COS-backed mount.  A signal handler + try/finally guarantee a final flush so
# no buffered output is lost when the container terminates.
#
# Custom jobs only have a public log: all lines go to the single file served
# by /logs to the job's author. [PUBLIC] and [PRIVATE] prefixes are stripped
# (equivalent to remove_prefix_tags_in_logs in core.domain.filter_logs).
import os, shutil, signal, subprocess, sys, threading

# Command to run (injected by the gateway template engine)
app_cmd = {{ app_cmd }}

# How often the logs are uploaded (seconds)
INTERVAL = int(os.environ.get('LOG_FLUSH_INTERVAL_SECONDS', 15))

# Max bytes kept in COS per log before truncating
LIMIT = int(os.environ.get('LOG_SIZE_LIMIT_BYTES', 52428800))

# Local path to COS mounted volume for public logs
COS_PUBLIC_PATH = os.environ['PUBLIC_LOG_PATH']

# Fast local buffer; periodically synced to COS
LOCAL_PUBLIC_LOG = '/tmp/public.log'

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

    def file_size(self, path):
        try:
            return os.path.getsize(path)
        except OSError:
            return -1

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
        if size > LIMIT:
            try:
                # Read the last LIMIT bytes from the local file
                with open(temporal_log_path, 'rb') as f:
                    f.seek(-LIMIT, 2)
                    tail = f.read()
                # Write the truncation header followed by the tail to COS
                with open(cos_path, 'wb') as f:
                    f.write(TRUNCATION_HEADER)
                    f.write(tail)
                # Shrink the local file to LIMIT, preserving the inode so the line-reader loop can keep writing to it
                with open(temporal_log_path, 'r+b') as f:
                    f.truncate(0)
                    f.seek(0)
                    f.write(tail)
            except OSError:
                pass
        else:
            try:
                shutil.copy(temporal_log_path, cos_path)
            except OSError:
                pass

    # Periodically copies the local log to COS, skipping no-op PUTs when the
    # app is silent.  Runs as a daemon thread so it is killed automatically on exit.
    def run_uploader_thread(self):
        last_size = -1
        while not self.stop.wait(INTERVAL):
            current_size = self.file_size(LOCAL_PUBLIC_LOG)
            if current_size != last_size:
                self.upload_log(LOCAL_PUBLIC_LOG, COS_PUBLIC_PATH)
                last_size = self.file_size(LOCAL_PUBLIC_LOG)

    # Stops the uploader thread (waits for any in-progress upload to finish),
    # then performs one final unconditional upload so the log on COS reflects
    # the very last lines written by the application.
    def flush(self):
        self.stop.set()
        if self.uploader_thread is not None:
            self.uploader_thread.join(timeout=5)
        self.upload_log(LOCAL_PUBLIC_LOG, COS_PUBLIC_PATH)

    def on_signal(self, sig, _frame):
        if self.user_process is not None:
            self.user_process.terminate()
        self.flush()
        # POSIX convention: exit code for signal-terminated processes is 128 + signal number
        sys.exit(128 + sig)

    # Strips [PUBLIC] and [PRIVATE] prefixes (case-insensitive) from a log line.
    def clean_line(self, line):
        if line[:len(PUBLIC_TAG)].upper() == PUBLIC_TAG:
            return line[len(PUBLIC_TAG) + 1:]
        if line[:len(PRIVATE_TAG)].upper() == PRIVATE_TAG:
            return line[len(PRIVATE_TAG) + 1:]
        return line

    def run(self):
        signal.signal(signal.SIGTERM, self.on_signal)  # container shutdown / kill
        signal.signal(signal.SIGINT, self.on_signal)   # Ctrl+C

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
        try:
            # Listen to changes in the local temporal log file
            with open(LOCAL_PUBLIC_LOG, 'a', buffering=1) as pub:
                # Process changes line by line
                for line in self.user_process.stdout:
                    # custom job logs are public, and it contains all the logs, just remove the prefixes
                    pub.write(self.clean_line(line))
                    pub.flush()
            code = self.user_process.wait()
        finally:
            self.flush()

        sys.exit(code)


JobWrapper().run()
{% endautoescape %}
