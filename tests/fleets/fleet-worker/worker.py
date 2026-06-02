"""Fleet worker that polls for job manifests in MinIO and executes them."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

from botocore.exceptions import ClientError

from storage import StorageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

FLEET_STATE_BUCKET = os.environ["FLEET_STATE_BUCKET"]
TASK_STORE_BUCKET = os.environ["TASK_STORE_BUCKET"]


class FleetWorker:
    """Polls for job manifests and executes them locally."""

    def __init__(self, *, storage: StorageManager) -> None:
        """Initialize the fleet worker.

        Args:
            storage: The storage manager handling S3 and s3fs operations.
        """
        self._storage = storage

    def run(self) -> None:
        """Enter the infinite poll loop. Does not return."""
        logger.info("Entering poll loop")
        while True:
            self._poll_once()
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
                except (ClientError, OSError, ValueError) as e:
                    logger.error("Error processing manifest %s: %s", key, e)

        except ClientError as e:
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
        logger.info("Processing manifest for fleet_id=%s job_id=%s", fleet_id, manifest.get("job_id"))

        volume_mounts = manifest.get("volume_mounts", [])
        self._setup_volume_mounts(volume_mounts)
        self._clean_temp_files()
        self._simulate_startup_delay()

        env_vars = manifest.get("env_vars", {})
        run_env = os.environ.copy()
        run_env.update(env_vars)

        for path_var in ("PUBLIC_LOG_PATH", "PRIVATE_LOG_PATH"):
            path = env_vars.get(path_var)
            if path:
                os.makedirs(os.path.dirname(path), exist_ok=True)

        exit_code = self._execute_commands(manifest.get("run_commands", []), run_env, fleet_id)
        self._cleanup()
        self._report_status(fleet_id, key, exit_code)

    def _setup_volume_mounts(self, volume_mounts: list[dict]) -> None:
        """Create symlinks for /data and /function_data.

        Args:
            volume_mounts: The volume_mounts from the manifest.
        """
        data_target, function_data_target = self._storage.resolve_symlink_targets(volume_mounts)
        if data_target:
            self._storage.create_symlink("/data", data_target)
        if function_data_target:
            self._storage.create_symlink("/function_data", function_data_target)

    def _execute_commands(self, run_commands: list[str], env: dict[str, str], fleet_id: str) -> int:
        """Run the job commands via subprocess.

        Args:
            run_commands: The command list to execute.
            env: The environment variables for the subprocess.
            fleet_id: The fleet ID (for logging).

        Returns:
            The process exit code (124 for timeout).
        """
        if not run_commands:
            return 0

        try:
            # Do NOT capture output — the wrapper uses tee/awk to write logs
            # to files via stdout. Let it flow to the s3fs mount.
            result = subprocess.run(run_commands, env=env, check=False, timeout=300)
            return result.returncode
        except subprocess.TimeoutExpired:
            logger.error("Job execution timed out for %s", fleet_id)
            return 124
        except OSError as e:
            logger.error("Failed to execute run_commands for %s: %s", fleet_id, e)
            return 1

    def _report_status(self, fleet_id: str, key: str, exit_code: int) -> None:
        """Write status to task-store and delete the consumed manifest.

        Args:
            fleet_id: The fleet ID.
            key: The manifest key to delete from fleet-state.
            exit_code: The process exit code (0 = succeeded).
        """
        status = "succeeded" if exit_code == 0 else "failed"
        logger.info("Fleet %s completed with status: %s (exit_code=%d)", fleet_id, status, exit_code)

        self._storage.client.put_object(
            Bucket=TASK_STORE_BUCKET,
            Key=f"{fleet_id}.status",
            Body=status.encode("utf-8"),
        )

        self._storage.client.delete_object(Bucket=FLEET_STATE_BUCKET, Key=key)
        logger.info("Manifest %s consumed and deleted", key)

    def _cleanup(self) -> None:
        """Remove symlinks and flush s3fs caches after job execution."""
        subprocess.run(["sync"], capture_output=True, check=False)
        time.sleep(2)
        self._storage.wait_for_visibility(["/data", "/function_data"])
        self._storage.remove_symlink("/data")
        self._storage.remove_symlink("/function_data")

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
