"""S3 storage and s3fs mount management for the fleet worker."""

from __future__ import annotations

import logging
import os
import subprocess
import time

import boto3

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.environ["MINIO_ENDPOINT"]
MINIO_ACCESS_KEY = os.environ["MINIO_ACCESS_KEY"]
MINIO_SECRET_KEY = os.environ["MINIO_SECRET_KEY"]
USER_DATA_BUCKET = os.environ["USER_DATA_BUCKET"]
PROVIDER_DATA_BUCKET = os.environ["PROVIDER_DATA_BUCKET"]

MOUNT_USER_DATA = "/mnt/user-data"
MOUNT_PROVIDER_DATA = "/mnt/provider-data"
S3FS_PASSWD_FILE = "/etc/s3fs-passwd"


class StorageManager:
    """Manages S3 client, s3fs FUSE mounts, and volume symlinks."""

    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        """Lazily create and cache the boto3 S3 client.

        Returns:
            A boto3 S3 client configured for the local MinIO instance.
        """
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=MINIO_ENDPOINT,
                aws_access_key_id=MINIO_ACCESS_KEY,
                aws_secret_access_key=MINIO_SECRET_KEY,
            )
        return self._client

    def setup_mounts(self) -> None:
        """Write s3fs credentials and mount user-data and provider-data buckets."""
        with open(S3FS_PASSWD_FILE, "w", encoding="utf-8") as f:
            f.write(f"{MINIO_ACCESS_KEY}:{MINIO_SECRET_KEY}")
        os.chmod(S3FS_PASSWD_FILE, 0o600)

        os.makedirs(MOUNT_USER_DATA, exist_ok=True)
        os.makedirs(MOUNT_PROVIDER_DATA, exist_ok=True)

        self._mount_bucket(USER_DATA_BUCKET, MOUNT_USER_DATA)
        self._mount_bucket(PROVIDER_DATA_BUCKET, MOUNT_PROVIDER_DATA)

        logger.info("Verifying user-data mount: %s", os.listdir(MOUNT_USER_DATA))
        logger.info("Verifying provider-data mount: %s", os.listdir(MOUNT_PROVIDER_DATA))
        print("s3fs mounts ready", flush=True)

    def _mount_bucket(self, bucket: str, mount_point: str) -> None:
        """Mount an S3 bucket via s3fs.

        Args:
            bucket: The S3 bucket name to mount.
            mount_point: The local filesystem path to mount the bucket at.

        Raises:
            RuntimeError: If the s3fs mount command fails.
        """
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

    def _bucket_to_mount(self, bucket: str) -> str:
        """Map a bucket name to its local s3fs mount point.

        Args:
            bucket: The S3 bucket name.

        Returns:
            The local mount path for the bucket.
        """
        if bucket == PROVIDER_DATA_BUCKET:
            return MOUNT_PROVIDER_DATA
        return MOUNT_USER_DATA

    def resolve_symlink_targets(self, volume_mounts: list[dict]) -> tuple[str | None, str | None]:
        """Resolve symlink targets from volume_mounts based on mount_path and bucket.

        Args:
            volume_mounts: List of volume mount dicts with mount_path, sub_path,
                and bucket keys.

        Returns:
            A tuple of (data_target, function_data_target) paths,
            each of which may be None if the corresponding mount is not present.
        """
        data_target = None
        function_data_target = None

        for vm in volume_mounts:
            mount_path = vm.get("mount_path", "")
            sub_path = vm.get("sub_path", "")
            bucket = vm.get("bucket", "")
            base = self._bucket_to_mount(bucket)
            if mount_path == "/data":
                data_target = os.path.join(base, sub_path)
            elif mount_path == "/function_data":
                function_data_target = os.path.join(base, sub_path)

        return data_target, function_data_target

    def create_symlink(self, link_path: str, target_path: str) -> None:
        """Create a symlink, removing any existing one first.

        Args:
            link_path: The path where the symlink will be created.
            target_path: The target directory the symlink will point to.
        """
        if os.path.islink(link_path) or os.path.exists(link_path):
            os.unlink(link_path)
        os.makedirs(target_path, exist_ok=True)
        os.symlink(target_path, link_path)
        logger.info("Symlink %s -> %s", link_path, target_path)

    def remove_symlink(self, link_path: str) -> None:
        """Remove a symlink if it exists.

        Args:
            link_path: The symlink path to remove.
        """
        try:
            if os.path.islink(link_path):
                os.unlink(link_path)
        except OSError:
            pass

    def _resolve_bucket_and_prefix(self, symlink_path: str) -> tuple[str, str] | None:
        """Resolve a symlink to its bucket and prefix by checking the real path.

        Args:
            symlink_path: A symlink path (e.g. /data, /function_data) that points
                into an s3fs mount.

        Returns:
            A (bucket, prefix) tuple, or None if the path doesn't resolve to
            a known mount.
        """
        if not os.path.islink(symlink_path):
            return None
        real = os.path.realpath(symlink_path)
        if real == MOUNT_USER_DATA or real.startswith(MOUNT_USER_DATA + "/"):
            return USER_DATA_BUCKET, real[len(MOUNT_USER_DATA):].lstrip("/")
        if real == MOUNT_PROVIDER_DATA or real.startswith(MOUNT_PROVIDER_DATA + "/"):
            return PROVIDER_DATA_BUCKET, real[len(MOUNT_PROVIDER_DATA):].lstrip("/")
        return None

    def wait_for_visibility(self, symlink_paths: list[str], *, timeout: int = 30) -> None:
        """Poll S3 until every file under each symlink is visible on the backend.

        s3fs flushes on close() but MinIO visibility is not guaranteed to be
        synchronous. Resolves each symlink to its bucket and prefix, walks the
        local tree, and waits for each file to appear via list_objects_v2.

        Args:
            symlink_paths: Symlink paths pointing into s3fs mounts (e.g.
                ["/data", "/function_data"]).
            timeout: Maximum seconds to wait for all files to become visible.
        """
        deadline = time.time() + timeout
        for path in symlink_paths:
            resolved = self._resolve_bucket_and_prefix(path)
            if not resolved or not os.path.isdir(path):
                continue
            bucket, prefix = resolved

            expected = set()
            for root, _, files in os.walk(path):
                for name in files:
                    full = os.path.join(root, name)
                    expected.add(os.path.relpath(full, path))
            if not expected:
                continue

            key_prefix = f"{prefix}/" if prefix else ""
            while True:
                resp = self.client.list_objects_v2(Bucket=bucket, Prefix=key_prefix)
                keys = {obj["Key"][len(key_prefix):] for obj in resp.get("Contents", [])}
                missing = expected - keys
                if not missing:
                    break
                if time.time() >= deadline:
                    logger.warning(
                        "Timeout waiting for S3 visibility on %s: missing %s",
                        path,
                        sorted(missing),
                    )
                    break
                time.sleep(0.5)
