"""COS client for Fleets-based jobs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

from core.services.storage.abstract_cos_client import AbstractCOSClient, COSError
from core.services.storage.enums.working_dir import WorkingDir

if TYPE_CHECKING:
    from core.models import Job

logger = logging.getLogger("FleetsCOSClient")


class FleetsCOSClient(AbstractCOSClient):
    """COS client for Fleets jobs.

    Routes requests to two separate buckets:
      - USER_STORAGE     → users/public bucket  (FLEETS_USERS_COS_*)
      - PROVIDER_STORAGE → partners/private bucket (FLEETS_PARTNERS_COS_*)
    """

    def __init__(self, job: Optional[Job] = None):
        self._job_id = str(job.id) if job else "-"
        self._users_client = None
        self._partners_client = None

    @property
    def _users_boto3_client(self):
        if self._users_client is None:
            self._users_client = boto3.client(
                "s3",
                endpoint_url=settings.FLEETS_USERS_COS_ENDPOINT,
                aws_access_key_id=settings.FLEETS_USERS_COS_ACCESS_KEY,
                aws_secret_access_key=settings.FLEETS_USERS_COS_SECRET_KEY,
            )
        return self._users_client

    @property
    def _partners_boto3_client(self):
        if self._partners_client is None:
            self._partners_client = boto3.client(
                "s3",
                endpoint_url=settings.FLEETS_PARTNERS_COS_ENDPOINT,
                aws_access_key_id=settings.FLEETS_PARTNERS_COS_ACCESS_KEY,
                aws_secret_access_key=settings.FLEETS_PARTNERS_COS_SECRET_KEY,
            )
        return self._partners_client

    def _resolve(self, working_dir: WorkingDir) -> tuple:
        """Return (boto3_client, bucket) for the given working_dir."""
        if working_dir == WorkingDir.PROVIDER_STORAGE:
            return self._partners_boto3_client, settings.FLEETS_PARTNERS_COS_BUCKET
        return self._users_boto3_client, settings.FLEETS_USERS_COS_BUCKET

    def get_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[str]:
        content = self.get_object_bytes(key, working_dir)
        return content.decode("utf-8") if content is not None else None

    def put_object(self, key: str, content: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> None:
        self.put_object_bytes(key, content.encode("utf-8"), working_dir)

    def get_object_bytes(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[bytes]:
        client, bucket = self._resolve(working_dir)
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                logger.info("[get_object_bytes] job_id=%s key=%s Object not found", self._job_id, key)
                return None
            raise COSError(f"Failed to get object [{key}]", e) from e

    def get_object_for_stream(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> Optional[bytes]:
        client, bucket = self._resolve(working_dir)
        try:
            response = client.get_object(Bucket=bucket, Key=key)
            return response["Body"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                logger.info("[get_object_bytes] job_id=%s key=%s Object not found", self._job_id, key)
                return None
            raise COSError(f"Failed to get object [{key}]", e) from e

    def put_object_bytes(self, key: str, content: bytes, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> None:
        client, bucket = self._resolve(working_dir)
        try:
            client.put_object(Bucket=bucket, Key=key, Body=content)
        except ClientError as e:
            raise COSError(f"Failed to put object [{key}]", e) from e

    def delete_object(self, key: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> bool:
        client, bucket = self._resolve(working_dir)
        try:
            client.delete_object(Bucket=bucket, Key=key)
            logger.info("[delete_object] job_id=%s key=%s Deleted", self._job_id, key)
            return True
        except ClientError as e:
            logger.error("[delete_object] job_id=%s key=%s error=%s", self._job_id, key, e)
            return False

    def list_objects(self, prefix: str, working_dir: WorkingDir = WorkingDir.USER_STORAGE) -> list[str]:
        client, bucket = self._resolve(working_dir)
        try:
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
            return [obj["Key"] for obj in response.get("Contents", [])]
        except ClientError as e:
            raise COSError(f"Failed to list objects with prefix [{prefix}]", e) from e
