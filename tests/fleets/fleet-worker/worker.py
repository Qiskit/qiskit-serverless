# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Fleet worker that polls for job manifests in MinIO and executes them."""

import json
import logging
import os
import signal
import subprocess
import time

from botocore.exceptions import BotoCoreError, ClientError

from storage import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Must match fleets_mock.py FLEET_STATE_BUCKET and docker-compose-fleets-test.yaml
FLEET_STATE_BUCKET = os.environ["FLEET_STATE_BUCKET"]
# Must match CE_PROJECTS.cos_bucket_task_store_name in docker-compose-fleets-test.yaml
TASK_STORE_BUCKET = os.environ["TASK_STORE_BUCKET"]


class FleetWorker:  # pylint: disable=too-few-public-methods
    """Polls for job manifests and executes them locally."""

    def __init__(self, *, storage: StorageManager) -> None:
        """Initialize the fleet worker.

        Args:
            storage: The storage manager handling S3 and s3fs operations.
        """
        self._storage = storage

    def run(self) -> None:
        """Enter the infinite poll loop. Does not return.

        Manifests are processed one at a time, inline — this worker is
        deliberately single-job-at-a-time (unlike real CE, which runs fleets in
        parallel). A long-running job blocks the queue for its duration, so
        tests must not submit overlapping long jobs.
        """
        logger.info("Entering poll loop")
        while True:
            try:
                self._poll_once()
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Never let a single bad cycle terminate the worker — a dead
                # worker stops processing all future jobs.
                logger.error("Unexpected error in poll loop (continuing): %s", e)
            time.sleep(1)

    def _poll_once(self) -> None:
        """List fleet-state bucket and process any manifest files found."""
        try:
            response = self._storage.client.list_objects_v2(Bucket=FLEET_STATE_BUCKET)
            contents = response.get("Contents", [])

            for obj in contents:
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue

                try:
                    manifest_obj = self._storage.client.get_object(Bucket=FLEET_STATE_BUCKET, Key=key)
                    manifest = json.loads(manifest_obj["Body"].read().decode("utf-8"))
                    self._process_manifest(key, manifest)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error("Bad manifest %s (quarantining): %s", key, e)
                    self._storage.client.delete_object(Bucket=FLEET_STATE_BUCKET, Key=key)
                except (ClientError, BotoCoreError, OSError, ValueError) as e:
                    logger.error("Error processing manifest %s: %s", key, e)

        except (ClientError, BotoCoreError) as e:
            logger.error("Error listing fleet-state bucket: %s", e)
        except OSError as e:
            logger.error("Unexpected error in poll loop: %s", e)

    def _process_manifest(self, key: str, manifest: dict) -> None:
        """Execute a job manifest and report status.

        Args:
            key: The S3 object key of the manifest in the fleet-state bucket.
            manifest: The parsed manifest dict containing volume_mounts,
                env_vars, and run_commands.
        """
        fleet_id = manifest.get("fleet_id") or key.replace(".json", "")
        project_id = manifest.get("project_id", "")
        logger.info("Processing manifest for fleet_id=%s job_id=%s", fleet_id, manifest.get("job_id"))

        # Claim the manifest by deleting it before executing, so a crash or
        # transient error mid-run cannot make the next poll re-run the user job
        # (at-most-once execution, mirroring CE's single dispatch).
        self._storage.client.delete_object(Bucket=FLEET_STATE_BUCKET, Key=key)

        self._write_cos_queue_key(project_id, fleet_id, "pending")

        exit_code = 1
        status = "failed"
        created_links: list[str] = []
        try:
            created_links = self._setup_volume_mounts(manifest.get("volume_mounts", []))
            self._clean_temp_files()
            self._simulate_startup_delay()

            self._write_cos_queue_key(project_id, fleet_id, "running")

            env_vars = manifest.get("env_vars", {})
            run_env = os.environ.copy()
            run_env.update(env_vars)

            for path_var in ("PUBLIC_LOG_PATH", "PRIVATE_LOG_PATH"):
                path = env_vars.get(path_var)
                if path:
                    os.makedirs(os.path.dirname(path), exist_ok=True)

            exit_code, canceled = self._execute_commands(
                manifest.get("run_commands", []), run_env, project_id, fleet_id
            )
            self._cleanup(created_links)

            # `canceled` is authoritative when the worker killed the process on
            # cancel. The post-execution recheck covers the race where the
            # process finished on its own just as cancel was signaled.
            if canceled or self._is_canceled(project_id, fleet_id):
                status = "canceled"
                logger.info("Fleet %s was canceled during execution — skipping final status write", fleet_id)
            else:
                status = "succeeded" if exit_code == 0 else "failed"
                self._write_cos_queue_key(project_id, fleet_id, f"{status}/{exit_code}")
        except (ClientError, BotoCoreError, OSError, ValueError) as e:
            # The manifest is already consumed, so a failure here must still
            # produce a terminal state rather than leaving the job stuck RUNNING.
            logger.error("Fleet %s failed during processing: %s", fleet_id, e)
            status = "failed"
            try:
                self._write_cos_queue_key(project_id, fleet_id, f"{status}/{exit_code}")
            except (ClientError, BotoCoreError) as write_err:
                logger.error("Failed to write terminal status for %s: %s", fleet_id, write_err)

        self._log_completion(fleet_id, status, exit_code)

    def _setup_volume_mounts(self, volume_mounts: list[dict]) -> list[str]:
        """Create symlinks for each volume mount path.

        Args:
            volume_mounts: The volume_mounts from the manifest.

        Returns:
            The list of symlink paths created (used to clean up exactly what was
            set up, rather than a hardcoded list that can drift).
        """
        targets = self._storage.resolve_symlink_targets(volume_mounts)
        for mount_path, target in targets.items():
            self._storage.create_symlink(mount_path, target)
        return list(targets)

    _EXECUTION_TIMEOUT_SEC = 300
    _CANCEL_POLL_INTERVAL_SEC = 1.0
    _TERMINATE_GRACE_SEC = 5

    def _execute_commands(
        self, run_commands: list[str], env: dict[str, str], project_id: str, fleet_id: str
    ) -> tuple[int, bool]:
        """Run the job commands via subprocess, terminating early on cancel.

        Uses Popen + a wait/poll loop (rather than a blocking subprocess.run)
        so the worker can detect a canceled queue key *during* execution and
        kill the subprocess — mirroring real Code Engine, which stops the
        workload on cancel. This also keeps the sequential poll loop from
        blocking on a long-running orphaned process.

        Args:
            run_commands: The command list to execute.
            env: The environment variables for the subprocess.
            project_id: The CE project UUID (for cancel detection).
            fleet_id: The fleet UUID (for cancel detection and logging).

        Returns:
            A ``(exit_code, canceled)`` tuple. ``exit_code`` is the process exit
            code (124 for timeout; negative signal number if terminated on
            cancel). ``canceled`` is True only when the worker killed the
            process in response to a cancel signal — the caller treats this as
            authoritative and skips writing a terminal status key.
        """
        if not run_commands:
            # An empty command list is a malformed manifest — flag it as failed
            # rather than reporting a success that executed no user code.
            logger.error("No run_commands for %s — treating as failed", fleet_id)
            return 1, False

        deadline = time.monotonic() + self._EXECUTION_TIMEOUT_SEC
        try:
            # Do NOT capture output — the wrapper uses tee/awk to write logs
            # to files via stdout. Let it flow to the s3fs mount.
            # start_new_session puts the child in its own process group so a
            # cancel/timeout can signal the whole tree, not just a wrapper that
            # may not forward the signal to the Python it spawned.
            #
            # Deliberately NOT using `with Popen(...)`: its __exit__ calls
            # wait() with no timeout, which would re-hang the single-threaded
            # poll loop on a wedged child. All waits below are bounded instead.
            # pylint: disable=consider-using-with
            proc = subprocess.Popen(run_commands, env=env, start_new_session=True)
            while True:
                try:
                    return proc.wait(timeout=self._CANCEL_POLL_INTERVAL_SEC), False
                except subprocess.TimeoutExpired:
                    pass

                if self._is_canceled(project_id, fleet_id):
                    logger.info("Fleet %s canceled during execution — terminating subprocess", fleet_id)
                    return self._terminate(proc), True

                if time.monotonic() >= deadline:
                    logger.error("Job execution timed out for %s", fleet_id)
                    self._signal_group(proc, signal.SIGKILL)
                    return self._reap(proc, 124), False
        except OSError as e:
            logger.error("Failed to execute run_commands for %s: %s", fleet_id, e)
            return 1, False

    def _terminate(self, proc: subprocess.Popen) -> int:
        """Terminate a subprocess group gracefully, escalating to kill if needed.

        Signals the whole process group (the child was started with
        start_new_session) so any process the wrapper spawned is stopped too.

        Args:
            proc: The running subprocess to stop.

        Returns:
            The process exit code after termination.
        """
        self._signal_group(proc, signal.SIGTERM)
        try:
            return proc.wait(timeout=self._TERMINATE_GRACE_SEC)
        except subprocess.TimeoutExpired:
            self._signal_group(proc, signal.SIGKILL)
            return self._reap(proc, -signal.SIGKILL)

    def _reap(self, proc: subprocess.Popen, default_code: int) -> int:
        """Wait (bounded) for an already-killed process, abandoning if wedged.

        A child stuck in uninterruptible sleep can ignore even SIGKILL; without
        a bounded wait the single-threaded poll loop would hang forever.

        Args:
            proc: The killed subprocess to reap.
            default_code: Exit code to report if the process never reaps.

        Returns:
            The real exit code, or ``default_code`` if reaping timed out.
        """
        try:
            return proc.wait(timeout=self._TERMINATE_GRACE_SEC)
        except subprocess.TimeoutExpired:
            logger.error("Subprocess %s did not exit after SIGKILL; abandoning", proc.pid)
            return default_code

    @staticmethod
    def _signal_group(proc: subprocess.Popen, sig: int) -> None:
        """Send a signal to the subprocess's whole process group.

        Falls back to signalling just the process if the group has already
        gone away (e.g. the process exited between poll and signal).

        Args:
            proc: The subprocess whose group to signal.
            sig: The signal to send (e.g. signal.SIGTERM).
        """
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except ProcessLookupError:
            pass
        except OSError:
            proc.send_signal(sig)

    @staticmethod
    def _queue_prefix(project_id: str, fleet_id: str) -> str:
        """Build the COS task-state queue key prefix for a fleet.

        Single source for the ``ce/{project}/{fleet}/v2/queue/`` layout so the
        cancel reader and the status writer cannot drift apart. Must stay in
        sync with the gateway FleetsRunner prefix.

        Args:
            project_id: The CE project UUID.
            fleet_id: The fleet UUID.

        Returns:
            The queue key prefix, ending in a trailing slash.
        """
        return f"ce/{project_id}/{fleet_id}/v2/queue/"

    def _is_canceled(self, project_id: str, fleet_id: str) -> bool:
        """Check if a canceled queue key exists for this job.

        Real Code Engine stops execution on cancel — the worker polls this
        during execution (to terminate the subprocess) and rechecks it after
        execution (to skip writing a terminal status key when cancellation was
        already signaled).

        Any COS error is treated as "not canceled" so a transient listing
        failure never escapes the in-execution poll loop: escaping would crash
        the worker and force ``Popen.__exit__`` to block on the still-running
        subprocess. ``ClientError`` covers HTTP-level errors and ``BotoCoreError``
        covers connectivity errors (e.g. ``EndpointConnectionError``); a missed
        cancel is simply retried on the next poll.

        Args:
            project_id: The CE project UUID.
            fleet_id: The fleet UUID.

        Returns:
            True if a canceled key exists in the task-store bucket.
        """
        prefix = self._queue_prefix(project_id, fleet_id) + "canceled/"
        try:
            response = self._storage.client.list_objects_v2(Bucket=TASK_STORE_BUCKET, Prefix=prefix, MaxKeys=1)
            return response.get("KeyCount", 0) > 0
        except (ClientError, BotoCoreError):
            return False

    def _write_cos_queue_key(self, project_id: str, fleet_id: str, status_path: str) -> None:
        """Write a COS task state queue key to simulate CE behavior.

        Args:
            project_id: The CE project UUID.
            fleet_id: The fleet UUID.
            status_path: The status segment (e.g. "pending", "running", "succeeded/0").
        """
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        prefix = self._queue_prefix(project_id, fleet_id)
        queue_key = f"{prefix}{status_path}/{fleet_id}-0/{timestamp}/000-00000-0/task-0"
        self._storage.client.put_object(
            Bucket=TASK_STORE_BUCKET,
            Key=queue_key,
            Body=b"",
        )
        logger.info("Wrote COS queue key: %s", queue_key)

    def _log_completion(self, fleet_id: str, status: str, exit_code: int) -> None:
        """Log the final job outcome.

        The manifest is already consumed at claim time (see _process_manifest),
        so this only records the resolved terminal state.

        Args:
            fleet_id: The fleet ID.
            status: The resolved job outcome ("succeeded", "failed", or "canceled").
            exit_code: The process exit code (0 = succeeded).
        """
        logger.info("Fleet %s completed with status: %s (exit_code=%d)", fleet_id, status, exit_code)

    def _cleanup(self, link_paths: list[str]) -> None:
        """Remove the job's symlinks and flush s3fs caches after execution.

        Args:
            link_paths: The symlink paths created for this job (from
                _setup_volume_mounts), so cleanup matches exactly what was set up.
        """
        subprocess.run(["sync"], capture_output=True, check=False)
        time.sleep(2)
        active_mounts = [p for p in link_paths if os.path.islink(p)]
        self._storage.wait_for_visibility(active_mounts)
        for mount_path in active_mounts:
            self._storage.remove_symlink(mount_path)

    def _clean_temp_files(self) -> None:
        """Remove leftover temp files from previous job runs."""
        for tmp_file in ("/tmp/public.log", "/tmp/private.log", "/tmp/app.status", "/tmp/app.pipe"):
            try:
                os.unlink(tmp_file)
            except OSError:
                pass

    def _simulate_startup_delay(self) -> None:
        """Sleep to simulate Code Engine fleet startup latency."""
        startup_delay = float(os.environ.get("FLEET_WORKER_STARTUP_DELAY_SEC", "5"))
        if startup_delay > 0:
            time.sleep(startup_delay)


def main() -> None:
    """Entry point: mount buckets and start polling for job manifests."""
    logger.info("Fleet worker starting")
    storage = StorageManager()
    storage.setup_mounts()
    worker = FleetWorker(storage=storage)
    worker.run()


if __name__ == "__main__":
    main()
