"""
IBM Cloud Object Storage (COS) client using boto3.
"""

import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger("gateway")


class COSClient:
    """Client for IBM Cloud Object Storage using S3-compatible API."""

    def __init__(self):
        self._client = None
        self._bucket = settings.COS_BUCKET

    @property
    def client(self):
        """Lazy load COS client."""
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.COS_ENDPOINT,
                aws_access_key_id=settings.COS_ACCESS_KEY,
                aws_secret_access_key=settings.COS_SECRET_KEY,
            )
        return self._client

    def get_object(self, key: str) -> Optional[str]:
        """Get object content from COS."""
        try:
            response = self.client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                logger.info("Object '%s' not found in bucket '%s'.", key, self._bucket)
                return None
            logger.error("Failed to get object '%s': %s", key, str(e))
            return None


cos_client = COSClient()
