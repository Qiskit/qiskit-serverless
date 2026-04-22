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
Integration test for FleetHandler against a live IBM Cloud Code Engine project.

Submits a fleet that mounts the user PDS at /data, runs a script that writes
a known marker line to the primary log via the fleet_utils logging wrapper,
waits for the fleet to succeed, then reads the log back from COS using
handler.cos.logs(). This exercises the full FleetHandler lifecycle including
PDS volume mounts and COS log retrieval — mirroring the write path used by
FleetsRunner (PR 4) without requiring the Django stack.

Prerequisites (see gateway/examples/setup_fleet_handler_integration_test_env.sh):

  Required:
    IBM_CLOUD_API_KEY              IBM Cloud API key
    CE_PROJECT_ID                  Code Engine project UUID
    CE_REGION                      Region (e.g. "us-east")
    CE_SUBNET_POOL_ID              Subnet pool ID for network_placements
    CE_PDS_NAME_STATE              Persistent data store for tasks_state_store
    CE_PDS_NAME_USERS              User PDS mounted at /data
    CE_TEST_IMAGE                  Container image reference
    CE_ICR_PULL_SECRET             Image pull secret name (if image is private)
    CE_HMAC_SECRET_ACCESS_KEY_ID   COS HMAC access key ID
    CE_HMAC_SECRET_ACCESS_KEY      COS HMAC secret access key
    CE_COS_BUCKET_USER_DATA_NAME   COS user data bucket name

Enable with:
  RUN_INTEGRATION_TESTS=1 .tox/shared/bin/pytest \\
      tests/core/services/ibm_cloud/code_engine/fleets/test_fleet_handler_integration.py -v -s
"""

import logging
import os
import time
import uuid

import pytest

from core.services.ibm_cloud.code_engine.fleets.fleet_utils import (
    build_run_commands,
    build_run_env_variables,
    build_run_volume_mounts,
)

_RUN = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN,
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

# Suppress noisy IBM SDK and boto3 loggers during integration runs
for _name in ("ibm_cloud_sdk_core", "ibm_botocore", "ibm_s3transfer", "urllib3"):
    logging.getLogger(_name).setLevel(logging.ERROR)

_TERMINAL_SUCCEEDED = {"succeeded", "successful"}
_TERMINAL_ALL = {"succeeded", "successful", "failed", "canceled"}


def _require_env(name: str) -> str:
    """Return the value of a required environment variable.

    Args:
        name: Environment variable name.

    Returns:
        The variable value.

    Raises:
        pytest.skip: If the variable is not set, skipping the test with a clear message.
    """
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Required env var {name!r} is not set")
    return value


@pytest.fixture(scope="module")
def client_provider():
    """Build an IBMCloudClientProvider from environment credentials.

    Returns:
        Initialized :class:`IBMCloudClientProvider`.
    """
    from core.services.ibm_cloud.clients import IBMCloudClientProvider  # pylint: disable=import-outside-toplevel

    api_key = _require_env("IBM_CLOUD_API_KEY")
    region = os.environ.get("CE_REGION", "us-east")
    return IBMCloudClientProvider(api_key=api_key, region=region)


@pytest.fixture(scope="module")
def handler(client_provider):
    """Build a FleetHandler wired to the live CE project with COS enabled.

    Args:
        client_provider: Live :class:`IBMCloudClientProvider` fixture.

    Returns:
        Initialized :class:`FleetHandler` with cos_config set.
    """
    from core.services.ibm_cloud.code_engine.fleets.fleet_handler import (
        FleetHandler,
    )  # pylint: disable=import-outside-toplevel

    project_id = _require_env("CE_PROJECT_ID")
    hmac_key_id = _require_env("CE_HMAC_SECRET_ACCESS_KEY_ID")

    cos_config: dict = {"hmac_access_key_id": hmac_key_id, "bucket_region": os.environ.get("CE_REGION", "us-east")}

    # If the secret is available directly, use it; otherwise rely on CE secret auto-discovery.
    hmac_secret = os.environ.get("CE_HMAC_SECRET_ACCESS_KEY")
    if hmac_secret:
        cos_config["hmac_secret_access_key"] = hmac_secret

    return FleetHandler(
        client_provider=client_provider,
        project_id=project_id,
        cos_config=cos_config,
    )


@pytest.mark.integration
def test_fleet_pds_cos_logs(handler):
    """Submit a fleet that writes a log to PDS-backed COS and verify it is readable.

    The fleet mounts the user PDS at /data with a test-scoped sub_path, runs a
    script via the fleet_utils logging wrapper that writes a known marker line to
    PRIMARY_LOG_PATH (/data/jobs/0/logs.log), waits for the fleet to succeed, then
    reads the log back from COS using handler.cos.logs().

    Args:
        handler: Live :class:`FleetHandler` fixture with cos_config set.
    """
    subnet_pool_id = _require_env("CE_SUBNET_POOL_ID")
    pds_name_state = _require_env("CE_PDS_NAME_STATE")
    pds_name_users = _require_env("CE_PDS_NAME_USERS")
    image_reference = _require_env("CE_TEST_IMAGE")
    user_bucket = _require_env("CE_COS_BUCKET_USER_DATA_NAME")
    image_secret = os.environ.get("CE_ICR_PULL_SECRET") or None

    # Use a single run_id as user_id, provider, and title — mirroring the
    # _build_cos_keys() pattern from test_fleets_runner_demo.py.
    run_id = f"integration-test-{uuid.uuid4().hex[:8]}"
    # job_id mirrors the Django job UUID used by fleets_runner._build_cos_paths()
    job_id = uuid.uuid4().hex
    user_function_prefix = f"users/{run_id}/provider_functions/{run_id}/{run_id}"
    fleet_name = run_id  # CE fleet names: lowercase alphanumeric and hyphens only
    fleet_id = None

    # COS layout mirrors fleets_runner._build_cos_paths() (user bucket, secondary/user log):
    #   PDS sub_path         = users/{run_id}/provider_functions/{run_id}/{run_id}
    #   PRIMARY_LOG_PATH     = /data/jobs/{job_id}/logs.log
    #   COS key              = {user_function_prefix}/jobs/{job_id}/logs.log
    log_marker = f"integration-log-ok-{run_id}"
    user_log_key = f"{user_function_prefix}/jobs/{job_id}/logs.log"

    try:
        run_volume_mounts = build_run_volume_mounts(mounts=[("/data", pds_name_users, user_function_prefix)])
        run_env_variables = build_run_env_variables(
            primary_mount_path=f"/data/jobs/{job_id}",
            primary_log_filename="logs.log",
        )
        run_commands = build_run_commands(
            app_run_commands=["sh", "-c", f"echo {log_marker}"],
        )

        print(f"\n[integration] run_id={run_id}")
        print(f"[integration] Submitting fleet: {fleet_name}")
        print(f"[integration] Expecting log at: {user_bucket}/{user_log_key}")

        fleet = handler.submit_job(
            name=fleet_name,
            image_reference=image_reference,
            network_placements=[{"type": "subnet_pool", "reference": subnet_pool_id}],
            scale_cpu_limit="1",
            scale_memory_limit="4G",
            scale_max_instances=1,
            scale_retry_limit=0,
            tasks_specification={"indices": "0"},
            tasks_state_store={"persistent_data_store": pds_name_state},
            image_secret=image_secret,
            extra_fields={
                "run_volume_mounts": run_volume_mounts,
                "run_env_variables": run_env_variables,
                "run_commands": run_commands,
            },
        )

        as_dict = fleet.to_dict() if hasattr(fleet, "to_dict") else dict(fleet)
        fleet_id = as_dict.get("id")
        assert fleet_id, "submit_job response missing 'id'"
        print(f"[integration] Fleet created: id={fleet_id}")

        print("[integration] Waiting for terminal state (timeout=300s)...")
        start = time.time()
        # Use _wait_until_state directly so the returned status avoids an extra
        # get_job_status call that could hit rate limits.
        final_status = handler._wait_until_state(  # pylint: disable=protected-access
            fleet_id,
            target_states=_TERMINAL_ALL,
            timeout_seconds=300,
            poll_interval_seconds=10,
        )
        elapsed = time.time() - start
        print(f"[integration] Terminal state reached in {elapsed:.1f}s: {final_status}")

        assert final_status in _TERMINAL_ALL, f"Fleet {fleet_id!r} ended with unexpected status {final_status!r}"
        assert final_status in _TERMINAL_SUCCEEDED, (
            f"Fleet {fleet_id!r} did not succeed — final status: {final_status!r}.\n"
            f"  project_id={os.environ.get('CE_PROJECT_ID')!r}  region={os.environ.get('CE_REGION')!r}\n"
            f"  Check IBM Cloud Logs (ICL) filtering by: codeengine.fleetId={fleet_id}"
        )

        print(f"[integration] Reading log from COS: {user_bucket}/{user_log_key}")
        log_content = handler.cos.logs(
            bucket_name=user_bucket,
            log_key=user_log_key,
            save_locally=False,
            wait_for_availability=True,
            timeout=120,
            poll_interval=10,
        )
        print(f"[integration] Log content: {log_content!r}")

        assert log_marker in log_content, f"Expected {log_marker!r} in log but got: {log_content!r}"
        print("[integration] Log verified.")

        print("[integration] Collecting worker resource allocations...")
        allocations = handler.workers.list_all_allocations(
            fleet_id=fleet_id,
            wait_for_completion=False,
        )
        for alloc in allocations:
            print(
                f"[integration] worker={alloc['worker_name']} "
                f"profile={alloc['profile']} "
                f"status={alloc['status']} "
                f"duration={alloc['last_duration_seconds']:.1f}s"
            )

    finally:
        if fleet_id:
            print(f"[integration] Cleaning up fleet: {fleet_id}")
            handler.delete_job(fleet_id)
