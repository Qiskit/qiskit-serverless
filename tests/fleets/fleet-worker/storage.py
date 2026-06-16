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

"""S3 storage and s3fs mount management for the fleet worker."""

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

    def resolve_symlink_targets(self, volume_mounts: list[dict]) -> dict[str, str]:
        """Resolve symlink targets from volume_mounts based on mount_path and bucket.

        Args:
            volume_mounts: List of volume mount dicts with mount_path, sub_path,
                and bucket keys.

        Returns:
            Dict mapping mount_path to resolved local filesystem path.
        """
        targets = {}
        for vm in volume_mounts:
            mount_path = vm.get("mount_path", "")
            sub_path = vm.get("sub_path", "")
            bucket = vm.get("bucket", "")
            base = self._bucket_to_mount(bucket)
            targets[mount_path] = os.path.join(base, sub_path)

        return targets

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

    def wait_for_visibility(self, symlink_paths: list[str], *, delay: float = 3) -> None:
        """Wait for s3fs writes to become visible on the S3 backend.

        Args:
            symlink_paths: Symlink paths pointing into s3fs mounts (used only
                for logging).
            delay: Seconds to wait after sync.
        """
        logger.info("Waiting %.1fs for S3 visibility on %s", delay, symlink_paths)
        time.sleep(delay)
