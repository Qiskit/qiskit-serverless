"""Fleet worker that polls for job manifests in MinIO and executes them."""

import json
import logging
import os
import subprocess
import time

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
FLEET_STATE_BUCKET = os.environ["FLEET_STATE_BUCKET"]
TASK_STORE_BUCKET = os.environ["TASK_STORE_BUCKET"]
USER_DATA_BUCKET = os.environ["USER_DATA_BUCKET"]
PROVIDER_DATA_BUCKET = os.environ["PROVIDER_DATA_BUCKET"]

MOUNT_USER_DATA = "/mnt/user-data"
MOUNT_PROVIDER_DATA = "/mnt/provider-data"
S3FS_PASSWD_FILE = "/etc/s3fs-passwd"


def create_s3_client():
    """Create a boto3 S3 client connected to MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )


def setup_s3fs_mounts():
    """Write s3fs credentials and mount user-data and provider-data buckets."""
    with open(S3FS_PASSWD_FILE, "w", encoding="utf-8") as f:
        f.write(f"{MINIO_ACCESS_KEY}:{MINIO_SECRET_KEY}")
    os.chmod(S3FS_PASSWD_FILE, 0o600)

    os.makedirs(MOUNT_USER_DATA, exist_ok=True)
    os.makedirs(MOUNT_PROVIDER_DATA, exist_ok=True)

    mount_bucket(USER_DATA_BUCKET, MOUNT_USER_DATA)
    mount_bucket(PROVIDER_DATA_BUCKET, MOUNT_PROVIDER_DATA)

    logger.info("Verifying user-data mount: %s", os.listdir(MOUNT_USER_DATA))
    logger.info("Verifying provider-data mount: %s", os.listdir(MOUNT_PROVIDER_DATA))
    print("s3fs mounts ready", flush=True)


def mount_bucket(bucket, mount_point):
    """Mount an S3 bucket via s3fs."""
    cmd = [
        "s3fs",
        bucket,
        mount_point,
        "-o",
        f"url={MINIO_ENDPOINT}",
        "-o",
        f"passwd_file={S3FS_PASSWD_FILE}",
        "-o",
        "use_path_request_style",
        "-o",
        "stat_cache_expire=1",
        "-o",
        "allow_other",
        "-o",
        "nonempty",
    ]
    logger.info("Mounting %s -> %s", bucket, mount_point)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.error("s3fs mount failed for %s: %s", bucket, result.stderr)
        raise RuntimeError(f"s3fs mount failed for {bucket}: {result.stderr}")
    logger.info("Mounted %s at %s", bucket, mount_point)


def resolve_symlink_targets(volume_mounts):
    """Resolve symlink targets from volume_mounts based on mount_path."""
    data_target = None
    function_data_target = None
    provider_logs_target = None

    for vm in volume_mounts:
        mount_path = vm.get("mount_path", "")
        sub_path = vm.get("sub_path", "")
        if mount_path == "/data":
            data_target = os.path.join(MOUNT_USER_DATA, sub_path)
        elif mount_path == "/function_data":
            function_data_target = os.path.join(MOUNT_PROVIDER_DATA, sub_path)
        elif mount_path == "/provider_logs":
            provider_logs_target = os.path.join(MOUNT_PROVIDER_DATA, sub_path)

    return data_target, function_data_target, provider_logs_target


def create_symlink(link_path, target_path):
    """Create a symlink, removing any existing one first."""
    if os.path.islink(link_path) or os.path.exists(link_path):
        os.unlink(link_path)
    os.makedirs(target_path, exist_ok=True)
    os.symlink(target_path, link_path)
    logger.info("Symlink %s -> %s", link_path, target_path)


def remove_symlink(link_path):
    """Remove a symlink if it exists."""
    try:
        if os.path.islink(link_path):
            os.unlink(link_path)
    except OSError:
        pass


def wait_for_s3_visibility(s3_client, volume_mounts, timeout=30):  # pylint: disable=too-many-locals
    """Poll S3 until every file under each mount is visible on the backend.

    s3fs flushes on close() but MinIO visibility is not guaranteed to be
    synchronous. We walk each mount locally and wait for each file to appear
    via list_objects_v2. Backstops the post-run ``sleep`` with a real check.
    """
    deadline = time.time() + timeout
    for vm in volume_mounts:
        mount_path = vm.get("mount_path", "")
        bucket = vm.get("bucket")
        sub_path = (vm.get("sub_path") or "").rstrip("/")
        if not bucket or not mount_path or not os.path.isdir(mount_path):
            continue

        expected = set()
        for root, _, files in os.walk(mount_path):
            for name in files:
                full = os.path.join(root, name)
                expected.add(os.path.relpath(full, mount_path))
        if not expected:
            continue

        prefix = f"{sub_path}/" if sub_path else ""
        while True:
            resp = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            keys = {obj["Key"][len(prefix) :] for obj in resp.get("Contents", [])}
            missing = expected - keys
            if not missing:
                break
            if time.time() >= deadline:
                logger.warning(
                    "Timeout waiting for S3 visibility on %s: missing %s",
                    mount_path,
                    sorted(missing),
                )
                break
            time.sleep(0.5)


def process_manifest(s3_client, key, manifest):  # pylint: disable=too-many-locals
    """Execute a job manifest and report status."""
    fleet_id = manifest.get("fleet_id") or key.replace(".json", "")
    logger.info("Processing manifest for fleet_id=%s job_id=%s", fleet_id, manifest.get("job_id"))

    volume_mounts = manifest.get("volume_mounts", [])
    data_target, function_data_target, provider_logs_target = resolve_symlink_targets(volume_mounts)

    if data_target:
        create_symlink("/data", data_target)
    if function_data_target:
        create_symlink("/function_data", function_data_target)
    if provider_logs_target:
        create_symlink("/provider_logs", provider_logs_target)

    env_vars = manifest.get("env_vars", {})
    run_env = os.environ.copy()
    run_env.update(env_vars)

    # Simulate Code Engine fleet startup. Real CE takes 1-2 minutes; trimmed
    # for CI and overridable via FLEET_WORKER_STARTUP_DELAY_SEC.
    startup_delay = float(os.environ.get("FLEET_WORKER_STARTUP_DELAY_SEC", "5"))
    if startup_delay > 0:
        time.sleep(startup_delay)

    run_commands = manifest.get("run_commands", [])
    exit_code = 0

    try:
        # Do NOT capture output — the run_commands wrapper uses tee/awk to
        # write logs to files via stdout. Let it flow to the s3fs mount.
        result = subprocess.run(run_commands, env=run_env, check=False, timeout=300)
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        logger.error("Job execution timed out for %s", fleet_id)
        exit_code = 124
    except OSError as e:
        logger.error("Failed to execute run_commands for %s: %s", fleet_id, e)
        exit_code = 1

    # Flush s3fs caches, then wait for MinIO to actually have the files.
    # NOTE: the sleep(2) also simulates post-run code execution tail — keep it
    # even though wait_for_s3_visibility below provides the real sync barrier.
    subprocess.run(["sync"], capture_output=True, check=False)
    time.sleep(2)
    wait_for_s3_visibility(s3_client, volume_mounts)

    remove_symlink("/data")
    remove_symlink("/function_data")
    remove_symlink("/provider_logs")

    status = "succeeded" if exit_code == 0 else "failed"
    logger.info("Fleet %s completed with status: %s (exit_code=%d)", fleet_id, status, exit_code)

    # Status goes to the task-store bucket (mirrors CE persistent task state).
    # The dispatch manifest in fleet-state is consumed and removed.
    s3_client.put_object(
        Bucket=TASK_STORE_BUCKET,
        Key=f"{fleet_id}.status",
        Body=status.encode("utf-8"),
    )

    s3_client.delete_object(Bucket=FLEET_STATE_BUCKET, Key=key)
    logger.info("Manifest %s consumed and deleted", key)


def poll_loop(s3_client):
    """Continuously poll for new job manifests.

    NOTE: assumes a single worker replica — manifests are not leased before
    execution, so multiple workers would double-execute the same job. Add
    a lease/lock (e.g. conditional rename to a `.processing` key) before
    scaling out.
    """
    logger.info("Entering poll loop")
    while True:
        try:
            response = s3_client.list_objects_v2(Bucket=FLEET_STATE_BUCKET)
            contents = response.get("Contents", [])

            for obj in contents:
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue

                try:
                    manifest_obj = s3_client.get_object(Bucket=FLEET_STATE_BUCKET, Key=key)
                    manifest = json.loads(manifest_obj["Body"].read().decode("utf-8"))
                    process_manifest(s3_client, key, manifest)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error("Bad manifest %s (quarantining): %s", key, e)
                    s3_client.delete_object(Bucket=FLEET_STATE_BUCKET, Key=key)
                except (ClientError, OSError, ValueError) as e:
                    logger.error("Error processing manifest %s: %s", key, e)

        except ClientError as e:
            logger.error("Error listing fleet-state bucket: %s", e)
        except OSError as e:
            logger.error("Unexpected error in poll loop: %s", e)

        time.sleep(1)


def main():
    """Entry point: mount buckets and start polling for job manifests."""
    logger.info("Fleet worker starting")
    setup_s3fs_mounts()
    s3_client = create_s3_client()
    poll_loop(s3_client)


if __name__ == "__main__":
    main()
