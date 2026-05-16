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

"""
Fleets mock layer for local integration tests.

When ``FLEETS_MOCK_ENABLED=1``, :func:`install_mocks` patches nine narrow
call sites that normally talk to IBM Cloud APIs, replacing them with
MinIO-based dispatch so that integration tests can run without real
IBM Cloud credentials.

Patches applied:

1. ``core.ibm_cloud.clients.IAMAuthenticator`` -- fake authenticator
2. ``api.services.authentication.ibm_quantum_platform.IAMAuthenticator`` -- same, second import site
3. ``IBMCloudClientProvider.get_cos_hmac_client`` -- MinIO-backed S3 client
4. ``core.ibm_cloud.get_cos_client`` -- returns a JobCOS wired to MinIO
5. ``core.services.runners.fleets_runner.get_cos_client`` -- same, bound import in runner
6. ``FleetHandler.submit_job`` -- writes manifest to MinIO ``fleet-state/``
7. ``FleetHandler.get_job_status`` -- reads status from MinIO ``task-store-bucket/``
8. ``FleetHandler.cancel_job`` -- no-op
9. ``FleetHandler.delete_job`` -- no-op
"""

from __future__ import annotations

import base64
import json
import logging
import os
import types
import uuid
from unittest.mock import patch

from django.conf import settings

logger = logging.getLogger("FleetsMock")

FLEET_STATE_BUCKET = "fleet-state"
FLEET_STATE_ARCHIVE_BUCKET = "fleet-state-archive"


def _task_store_bucket() -> str:
    """Bucket where the worker writes ``<fleet_id>.status``.

    Mirrors CE's persistent task state. Sourced from the same env var the
    gateway sets (``CE_COS_BUCKET_TASK_STORE_NAME``) so the compose file is
    the single source of truth.
    """
    return os.environ["CE_COS_BUCKET_TASK_STORE_NAME"]


_patches: list = []


def _minio_endpoint() -> str:
    return os.environ["MINIO_ENDPOINT"]


def _minio_access_key() -> str:
    return os.environ["MINIO_ACCESS_KEY"]


def _minio_secret_key() -> str:
    return os.environ["MINIO_SECRET_KEY"]


def _make_mock_s3_client():
    """Create an ibm_boto3 S3 client pointing at MinIO for fleet-state operations."""
    from ibm_boto3 import client as ibm_boto3_client  # pylint: disable=import-outside-toplevel

    return ibm_boto3_client(
        "s3",
        aws_access_key_id=_minio_access_key(),
        aws_secret_access_key=_minio_secret_key(),
        endpoint_url=_minio_endpoint(),
    )


_MOCK_S3: tuple[int, object] | None = None


def _get_mock_s3():
    """Return a per-process MinIO S3 client for fleet-state operations.

    Keyed on pid so gunicorn forks don't inherit the parent's socket.
    """
    global _MOCK_S3  # pylint: disable=global-statement
    pid = os.getpid()
    if _MOCK_S3 is None or _MOCK_S3[0] != pid:
        _MOCK_S3 = (pid, _make_mock_s3_client())
    return _MOCK_S3[1]


def _make_fake_jwt() -> str:
    """Build a minimal decodable JWT with iam_id and account.bss fields."""
    header_json = json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    header = base64.urlsafe_b64encode(header_json).rstrip(b"=").decode()
    payload_data = {
        "iam_id": "iam-mock-fleets-test",
        "account": {"bss": "mock-account-id"},
        "sub": "mock-subject",
        "iss": "https://iam.mock.cloud.ibm.com",
    }
    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(b"mock-signature").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


class _FakeTokenManager:  # pylint: disable=too-few-public-methods
    """Mimics the IAM SDK token manager interface."""

    def __init__(self):
        self._token = _make_fake_jwt()

    def get_token(self) -> str:
        """Return the fake JWT token."""
        return self._token


class _FakeIAMAuthenticator:
    """Drop-in replacement for ``ibm_cloud_sdk_core.authenticators.IAMAuthenticator``.

    Accepts both ``apikey`` (keyword used by the real SDK and
    ``ibm_quantum_platform.py``) and a positional first arg (used by
    ``IBMCloudClientProvider`` which passes the key positionally).
    """

    def __init__(self, apikey: str = "", *, url: str = "", **kwargs):  # pylint: disable=unused-argument
        self.token_manager = _FakeTokenManager()

    def validate(self):
        """No-op validation."""

    def authenticate(self, req):
        """No-op authentication."""


def _mock_get_cos_hmac_client(
    self, *, access_key_id, secret_access_key, bucket_region=None, endpoint_url=None  # pylint: disable=unused-argument
):
    """Return an ibm_boto3 S3 client pointing at MinIO for user/provider data buckets."""
    from ibm_boto3 import client as ibm_boto3_client  # pylint: disable=import-outside-toplevel

    return ibm_boto3_client(
        "s3",
        aws_access_key_id=_minio_access_key(),
        aws_secret_access_key=_minio_secret_key(),
        endpoint_url=_minio_endpoint(),
    )


def _mock_get_cos_client(project):  # pylint: disable=unused-argument
    """Return a JobCOS wired directly to MinIO, bypassing CE secret retrieval.

    The upstream ``get_cos_client`` factory fetches HMAC credentials from a
    Code Engine secret via ``SecretsAndConfigmapsApi.get_secret``. In the
    mock environment there is no real CE backend, so we build the JobCOS
    directly. The underlying S3 client still flows through the patched
    ``IBMCloudClientProvider.get_cos_hmac_client``, which routes to MinIO.
    """
    # pylint: disable=import-outside-toplevel
    from core.ibm_cloud.clients import IBMCloudClientProvider
    from core.ibm_cloud.code_engine.fleets.cos import JobCOS
    from core.ibm_cloud.cos.cos_client import COSClient, CosHmacCredentials

    client_provider = IBMCloudClientProvider(api_key=settings.IBM_CLOUD_API_KEY, region=project.region)
    cos_client = COSClient(
        client_provider=client_provider,
        credentials=CosHmacCredentials(
            access_key_id=_minio_access_key(),
            secret_access_key=_minio_secret_key(),
        ),
        bucket_region=project.region,
        endpoint_url=_minio_endpoint(),
    )
    return JobCOS(cos_client)


def _pds_reference_to_bucket(reference: str) -> str:
    """Map a PDS reference name to its COS bucket name via Django settings.

    Raises ``ValueError`` on unknown references — fails loudly rather than
    letting ``None`` propagate into the manifest and surface as a KeyError
    in the worker. Missing bucket settings will raise ``AttributeError`` via
    direct attribute access.
    """
    pds_users = getattr(settings, "CE_PDS_NAME_USERS", None)
    pds_providers = getattr(settings, "CE_PDS_NAME_PROVIDERS", None)

    if pds_users and reference == pds_users:
        return settings.CE_COS_BUCKET_USER_DATA_NAME
    if pds_providers and reference == pds_providers:
        return settings.CE_COS_BUCKET_PROVIDER_DATA_NAME

    raise ValueError(
        f"Unknown PDS reference {reference!r} — expected one of "
        f"{pds_users!r} (users) or {pds_providers!r} (providers)"
    )


def _mock_submit_job(self, **kwargs):  # pylint: disable=unused-argument,too-many-locals
    """Write a fleet manifest to MinIO instead of calling Code Engine."""
    s3 = _get_mock_s3()
    fleet_id = str(uuid.uuid4())

    extra_fields = kwargs.get("extra_fields") or {}

    # Volume mounts
    raw_mounts = extra_fields.get("run_volume_mounts", [])
    volume_mounts = []
    for mount in raw_mounts:
        bucket = _pds_reference_to_bucket(mount.get("reference", ""))
        volume_mounts.append(
            {
                "mount_path": mount.get("mount_path", ""),
                "bucket": bucket,
                "sub_path": mount.get("sub_path", ""),
            }
        )

    # Environment variables: [{type, name, value}, ...] -> {name: value, ...}
    raw_env = extra_fields.get("run_env_variables", [])
    env_vars = {}
    for entry in raw_env:
        name = entry.get("name", "")
        value = entry.get("value", "")
        if name:
            env_vars[name] = value

    # Run commands (already a list)
    run_commands = extra_fields.get("run_commands", [])

    # Extract job_id from env vars
    job_id = env_vars.get("ENV_JOB_ID_GATEWAY", "")

    manifest = {
        "fleet_id": fleet_id,
        "job_id": job_id,
        "volume_mounts": volume_mounts,
        "env_vars": env_vars,
        "run_commands": run_commands,
    }

    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    s3.put_object(Bucket=FLEET_STATE_BUCKET, Key=f"{fleet_id}.json", Body=manifest_bytes)
    s3.put_object(Bucket=FLEET_STATE_ARCHIVE_BUCKET, Key=f"{fleet_id}.json", Body=manifest_bytes)

    logger.info("Mock submit_job: fleet_id=%s job_id=%s", fleet_id, job_id)

    result = types.SimpleNamespace()
    result.to_dict = lambda: {"id": fleet_id}
    return result


def _mock_get_job_status(self, identifier):  # pylint: disable=unused-argument
    """Check the task-store bucket for fleet status instead of calling Code Engine."""
    from ibm_botocore.exceptions import ClientError  # pylint: disable=import-outside-toplevel

    s3 = _get_mock_s3()
    fleet_id = identifier

    status_key = f"{fleet_id}.status"
    try:
        resp = s3.get_object(Bucket=_task_store_bucket(), Key=status_key)
        content = resp["Body"].read().decode("utf-8").strip()
        status = content
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            status = "pending"
        else:
            raise

    return {
        "id": fleet_id,
        "name": f"mock-fleet-{fleet_id[:8]}",
        "status": status,
        "desired_instances": 1,
        "running_instances": 1 if status in ("running", "succeeded") else 0,
        "created_at": None,
        "updated_at": None,
        "raw": {},
    }


def _mock_cancel_job(self, identifier, **kwargs):  # pylint: disable=unused-argument
    """No-op cancel."""


def _mock_delete_job(self, identifier):  # pylint: disable=unused-argument
    """No-op delete."""


def install_mocks():
    """Apply all fleet mock patches at module level.

    Call once during app startup (``CoreConfig.ready()``) when
    ``FLEETS_MOCK_ENABLED=1``. Patches persist for the lifetime of
    the process.
    """
    if _patches:
        logger.warning("Fleets mocks already installed — skipping")
        return

    patches = [
        patch(
            "core.ibm_cloud.clients.IAMAuthenticator",
            _FakeIAMAuthenticator,
        ),
        # Also patch the ibm_quantum_platform import site. mock_token auth
        # bypasses it today, but custom_token imports IAMAuthenticator directly
        # and would hit real IAM without this patch.
        patch(
            "api.services.authentication.ibm_quantum_platform.IAMAuthenticator",
            _FakeIAMAuthenticator,
        ),
        patch(
            "core.ibm_cloud.clients.IBMCloudClientProvider.get_cos_hmac_client",
            _mock_get_cos_hmac_client,
        ),
        patch(
            "core.ibm_cloud.get_cos_client",
            _mock_get_cos_client,
        ),
        # fleets_runner imports get_cos_client by name, so patch the bound
        # reference in the runner module too — patching only the source
        # module would miss already-imported names.
        patch(
            "core.services.runners.fleets_runner.get_cos_client",
            _mock_get_cos_client,
        ),
        patch(
            "core.ibm_cloud.code_engine.fleets.handler.FleetHandler.submit_job",
            _mock_submit_job,
        ),
        patch(
            "core.ibm_cloud.code_engine.fleets.handler.FleetHandler.get_job_status",
            _mock_get_job_status,
        ),
        patch(
            "core.ibm_cloud.code_engine.fleets.handler.FleetHandler.cancel_job",
            _mock_cancel_job,
        ),
        patch(
            "core.ibm_cloud.code_engine.fleets.handler.FleetHandler.delete_job",
            _mock_delete_job,
        ),
    ]

    for p in patches:
        p.start()
        _patches.append(p)

    logger.info(
        "Fleets mock installed: %d patches active (MinIO endpoint=%s)",
        len(_patches),
        _minio_endpoint(),
    )
