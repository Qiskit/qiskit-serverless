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

"""Unit tests for FleetsRunner."""

import io
import tarfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings as django_settings
from ibm_botocore.exceptions import ClientError
from ibm_botocore.exceptions import ReadTimeoutError as CosReadTimeoutError
from urllib3.exceptions import MaxRetryError, NameResolutionError, NewConnectionError, ProtocolError
from urllib3.exceptions import ReadTimeoutError as HttpReadTimeoutError

from core.domain.compute_profile import normalize as normalize_compute_profile
from core.ibm_cloud.code_engine.ce_client.rest import ApiException
from core.ibm_cloud.code_engine.fleets.utils import FleetJobPaths, build_job_paths
from core.models import CodeEngineProject, Job, Program
from core.clients.runtime_api_errors import RuntimeApiError
from core.domain.exceptions.retryable_error import RetryableError
from core.services.runners.abstract_runner import CosRetryableError, RunnerError, RunnerRetryableError
from core.services.runners import fleets_runner as fleets_runner_module
from core.services.runners.fleets_runner import FleetsRunner
from tests.utils import TestUtils

_RUNNER_MOD = "core.services.runners.fleets_runner"


@pytest.fixture(autouse=True)
def job_not_mirrored():
    """These tests do not use the database, so whether the job is mirrored is patched instead of looked up."""
    with patch.object(fleets_runner_module, "is_mirrored", return_value=False) as is_mirrored:
        yield is_mirrored


def _make_runner(fleet_id: str | None = None) -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner wired to mock Job and FleetHandler.

    Args:
        fleet_id: Optional fleet ID to pre-set on the job.

    Returns:
        Tuple of ``(runner, mock_handler)``.
    """
    mock_job = MagicMock()
    mock_job.fleet_id = fleet_id
    mock_job.filler = False
    mock_job.ce_project_name = None
    mock_job.status = Job.SUCCEEDED
    mock_job.program.title = "my-function"
    mock_job.author.username = "IBMid-1000000000"
    mock_job.SUCCEEDED = "SUCCEEDED"
    mock_job.FAILED = "FAILED"
    mock_job.STOPPED = "STOPPED"
    mock_job.PENDING = "PENDING"
    mock_job.RUNNING = "RUNNING"

    runner = FleetsRunner(mock_job)
    mock_handler = MagicMock()
    mock_cos = MagicMock()
    mock_cos.list_keys.return_value = []
    mock_project = MagicMock()
    mock_project.cos_bucket_task_store_name = "task-store-bucket"
    mock_project.project_id = "test-project-id"
    mock_job.program.code_engine_project = mock_project
    runner._handler = mock_handler  # pylint: disable=protected-access
    runner._project = mock_project  # pylint: disable=protected-access
    runner._cos = mock_cos  # pylint: disable=protected-access
    runner._connected = True  # pylint: disable=protected-access
    return runner, mock_handler


@contextmanager
def _patch_settings(**overrides):
    """Mock Django settings with sensible defaults for FleetsRunner tests."""
    defaults = {
        "CE_HMAC_SECRET_NAME": None,
        "IBM_CLOUD_API_KEY": "test-api-key",
        "CE_ICR_PULL_SECRET": "test-pull-secret",
        "FLEETS_DEFAULT_IMAGE": "default-image:latest",
        "DEFAULT_COMPUTE_PROFILE": "cx3d-4x16",
        "FLEETS_GATEWAY_HOST": None,
        "CUSTOM_IMAGE_PACKAGE_PATH": "/runner",
        "CUSTOM_IMAGE_PACKAGE_NAME": "runner",
        # Rendered into the fleet wrapper templates; must be a real string so json.dumps works.
        "QISKIT_USER_CONFIG": "[default]\nmin_qpy_version = 13\n",
    }
    defaults.update(overrides)
    with (
        patch(f"{_RUNNER_MOD}.settings") as mock_settings,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        for key, value in defaults.items():
            setattr(mock_settings, key, value)
        yield mock_settings


def _make_submit_runner() -> tuple[FleetsRunner, MagicMock]:
    """Build a FleetsRunner pre-wired for submit() with COS configured.

    COS interactions are mocked: _upload_program_to_cos is patched to a no-op
    so tests that verify fleet submission parameters don't need real COS credentials.

    Returns:
        Tuple of ``(runner, mock_handler)`` where handler.submit_job
        returns a fleet with id="fleet-abc".
    """
    mock_job = MagicMock()
    mock_job.fleet_id = None
    mock_job.id = "job-uuid"
    mock_job.filler = False
    mock_job.SUCCEEDED = "SUCCEEDED"
    mock_job.FAILED = "FAILED"
    mock_job.STOPPED = "STOPPED"
    mock_job.PENDING = "PENDING"
    mock_job.RUNNING = "RUNNING"
    mock_job.config = None
    mock_job.compute_profile_id = None
    mock_job.program.title = "my-function"
    mock_job.author.username = "IBMid-1000000000"
    mock_job.program.image = None
    mock_job.program.artifact = None
    mock_job.program.entrypoint = "main.py"
    mock_job.program.provider = None
    mock_job.program.runner = Program.FLEETS
    mock_job.env_vars = "{}"
    mock_job.arguments = "{}"

    runner = FleetsRunner(mock_job)
    mock_handler = MagicMock()
    runner._handler = mock_handler  # pylint: disable=protected-access

    mock_project = MagicMock()
    mock_project.subnet_pool_id = "subnet-1"
    mock_project.pds_name_state = "state-pds"
    mock_project.project_name = "test-project"
    mock_project.cos_bucket_user_data_name = "user-bucket"
    mock_project.cos_bucket_provider_data_name = "provider-bucket"
    mock_project.cos_instance_name = "cos-instance"
    mock_project.cos_key_name = "cos-key"
    mock_project.pds_name_users = "user-pds"
    mock_project.pds_name_providers = "provider-pds"
    runner._project = mock_project  # pylint: disable=protected-access
    runner._connected = True  # pylint: disable=protected-access

    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": "fleet-abc"}
    mock_handler.submit_job.return_value = mock_fleet
    runner._cos = MagicMock()  # pylint: disable=protected-access

    return runner, mock_handler


def test_is_active_true_when_fleet_id_set():
    """is_active() returns True when job has a fleet_id."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    assert runner.is_active() is True


def test_is_active_false_when_no_fleet_id():
    """is_active() returns False when job.fleet_id is None."""
    runner, _ = _make_runner(fleet_id=None)
    assert runner.is_active() is False


def test_status_raises_runner_error_when_no_fleet_id():
    """status() raises RunnerError when job has no fleet_id."""
    runner, _ = _make_runner(fleet_id=None)

    with pytest.raises(RunnerError, match="fleet_id"):
        runner.status()


@pytest.fixture(autouse=True)
def _clear_unresolved_warned():
    """Keep tests independent of the runner's per-fleet warning throttle.

    The throttle is module state so the scheduler warns once per fleet rather than
    once per poll, which would otherwise make these tests order dependent.
    """
    fleets_runner_module._UNRESOLVED_WARNED.clear()
    yield
    fleets_runner_module._UNRESOLVED_WARNED.clear()


def _cos_by_version(keys_by_version):
    """Build a ``list_keys`` stub that answers per task-store schema version.

    status() lists one version prefix at a time, so a stub with a single
    return_value would hand v2 keys back when the runner asked for v3.

    Args:
        keys_by_version: Mapping of version segment ("v3", "v2") to the keys that
            version holds.

    Returns:
        A callable suitable for ``list_keys.side_effect``.
    """

    def _list_keys(*, bucket_name, prefix):  # pylint: disable=unused-argument
        for version, keys in keys_by_version.items():
            if f"/{version}/queue/" in prefix:
                return keys
        return []

    return _list_keys


_V3 = "ce/test-project-id/fleet-123/v3/queue/"
_V2 = "ce/test-project-id/fleet-123/v2/queue/"
_TASK = "000-00000-0/default/8d76aa17-efb0-56da-88fd-488e8444b46d"
_WORKER = "fleet-123-0"
_T0, _T1, _T2 = "2026-08-26T19:09:39Z", "2026-08-26T19:10:14Z", "2026-08-26T19:11:05Z"

# Segment orders observed on real v3 fleets in staging (pending, running, succeeded, failed).
# Note succeeded and failed use different result-code forms, "exit_0" against
# "error_exit_1", and failed carries an extra retry segment, which is precisely why the
# reader reads only the state segment and treats the rest as opaque. The canceled shape
# is the documented one rather than a measured one: cancelling a real fleet wrote no
# canceled queue key at all, on either schema version, so only our test harness
# produces one.
_V3_PENDING = f"{_V3}pending/000-00000-0/default/0/{_T0}/8d76aa17"
_V3_RUNNING = f"{_V3}running/{_WORKER}/{_T1}/{_T0}/{_TASK}"
_V3_SUCCEEDED = f"{_V3}succeeded/exit_0/{_WORKER}/{_T2}/{_T1}/{_T0}/{_TASK}"
_V3_FAILED = f"{_V3}failed/error_exit_1/{_WORKER}/{_T2}/{_T1}/{_T0}/0/{_TASK}"
_V3_CANCELED = f"{_V3}canceled/{_WORKER}/{_T2}/{_T1}/{_T0}/{_TASK}"


def test_status_returns_none_when_cos_empty():
    """status() returns None when COS has no keys yet (fleet just created)."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    runner._cos.list_keys.return_value = []

    assert runner.status() is None


class TestCosStatusDetection:
    """Tests for COS-based fleet status detection."""

    def test_v3_pending_returns_pending(self):
        """status() returns PENDING from a v3 pending key."""
        runner, mock_handler = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_PENDING]})

        assert runner.status() == Job.PENDING
        mock_handler.get_job_status.assert_not_called()

    def test_v3_running_returns_running(self):
        """status() returns RUNNING from a v3 running key."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_RUNNING]})

        assert runner.status() == Job.RUNNING

    def test_v3_succeeded_returns_succeeded(self):
        """status() returns SUCCEEDED from a v3 succeeded key, result code and all."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_SUCCEEDED]})

        assert runner.status() == Job.SUCCEEDED

    def test_v3_failed_returns_failed(self):
        """status() returns FAILED from a v3 failed key."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_FAILED]})

        assert runner.status() == Job.FAILED

    def test_v3_canceled_returns_stopped(self):
        """status() returns STOPPED from a v3 canceled key."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_CANCELED]})

        assert runner.status() == Job.STOPPED

    def test_v2_keys_still_read_through_the_fallback(self):
        """A fleet on the legacy layout is read when v3 holds nothing."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version(
            {"v2": [f"{_V2}succeeded/0/{_WORKER}/2026-01-01T00:00:00Z/..."]}
        )

        assert runner.status() == Job.SUCCEEDED
        assert runner._cos.list_keys.call_count == 2

    def test_terminal_state_takes_priority_over_running(self):
        """A terminal key wins even when a running key is present too."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3_RUNNING, _V3_SUCCEEDED]})

        assert runner.status() == Job.SUCCEEDED

    def test_batch_name_cannot_forge_a_terminal_state(self):
        """A batch named after a state does not change the answer.

        The batch name is user supplied and appears deeper in the key, so only the
        segment straight after ``queue/`` may decide the status.
        """
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version(
            {"v3": [f"{_V3}pending/000-00000-0/succeeded/0/{_T0}/8d76aa17"]}
        )

        assert runner.status() == Job.PENDING

    def test_directory_marker_alone_returns_none(self):
        """A zero-byte ``queue/`` marker carries no state."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [_V3]})

        assert runner.status() is None

    def test_unknown_state_returns_none_without_raising(self):
        """An unrecognised state is reported as no status, never as a failure.

        Raising here would make the scheduler mark the job FAILED, so a single
        Code Engine rename would fail every in-flight job at once.
        """
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = _cos_by_version({"v3": [f"{_V3}unknown-state/x"]})

        assert runner.status() is None

    def test_cos_failure_does_not_probe_the_other_version(self):
        """A COS fault stops the version walk instead of repeating the failure."""
        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = Exception("connection error")

        assert runner.status() is None
        assert runner._cos.list_keys.call_count == 1

    def test_cos_client_error_returns_none(self):
        """status() returns None when COS raises ClientError."""
        from ibm_botocore.exceptions import ClientError

        runner, _ = _make_runner(fleet_id="fleet-123")
        runner._cos.list_keys.side_effect = ClientError(
            {"Error": {"Code": "NoSuchBucket", "Message": "not found"}},
            "ListObjectsV2",
        )

        assert runner.status() is None


def test_stop_returns_false_when_the_program_is_deleted():
    """Nothing can cancel this fleet or confirm it stopped, so the caller must end the row."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner.job.program = None

    assert runner.stop() is False
    mock_handler.cancel_job.assert_not_called()


@pytest.mark.parametrize(
    "break_it",
    [
        lambda job: setattr(job.program, "code_engine_project", None),
        lambda job: setattr(job.program.code_engine_project, "active", False),
    ],
    ids=["no-project", "project-inactive"],
)
def test_stop_raises_when_the_project_can_be_put_back(break_it):
    """An operator can assign or re-activate the project, so this must not become a terminal status:
    that would strand a fleet still holding its node. Not retryable either, or one deactivated
    project would open its whole region's breaker and pause everyone else's submits.

    Goes through the real stop() on purpose. Injecting the error into a mocked runner hides which
    type it reports, which is the thing every caller branches on.
    """
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    break_it(runner.job)

    with pytest.raises(RunnerError) as exc:
        runner.stop()

    assert type(exc.value) is RunnerError
    mock_handler.cancel_job.assert_not_called()


def test_stop_returns_true_when_the_cancel_was_accepted():
    """stop() reports True only when Code Engine accepted the cancel."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cancel_job.return_value = True

    result = runner.stop()

    assert result is True
    mock_handler.cancel_job.assert_called_once_with("fleet-123", wait=False, delete=False)


def test_stop_returns_false_when_there_was_nothing_to_cancel():
    """stop() reports False when Code Engine says the fleet is gone.

    It still sends the cancel, and it does not read the fleet status to decide. That pre-read is
    what stopped a fleet in an unrecognised status from being cancelled at all, so assert it is
    gone rather than just that the result is right.
    """
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cancel_job.return_value = False

    result = runner.stop()

    assert result is False
    mock_handler.cancel_job.assert_called_once_with("fleet-123", wait=False, delete=False)
    mock_handler.get_job_status.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ApiException(status=429, reason="Too Many Requests"),
        ApiException(status=503, reason="Service Unavailable"),
        ApiException(status=0, reason="no answer"),
        ApiException(status=403, reason="Forbidden"),
        ApiException(status=400, reason="Bad Request"),
        MaxRetryError(None, "/", reason=NewConnectionError(None, "refused")),
        MaxRetryError(None, "/", reason=NameResolutionError("api.wrong.example.com", None, "not found")),
        MaxRetryError(None, "/", reason=ProtocolError()),
        CosReadTimeoutError(endpoint_url="/"),
    ],
    ids=["429", "503", "no-answer", "403", "400", "refused", "bad-dns", "protocol", "read-timeout"],
)
def test_stop_asks_again_for_every_cancel_that_did_not_land(error):
    """A 400, a 403 and a bad region are all something that gets fixed, and sending the same cancel
    twice is safe because one already in flight answers 409. A submit cannot say that, which is why
    it keeps a permanent class and fails the job instead."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cancel_job.side_effect = error

    with pytest.raises(RunnerError) as exc:
        runner.stop()

    assert type(exc.value) is RunnerRetryableError


def test_stop_reports_an_iam_failure_during_the_cancel_as_retryable():
    """The token is read per request now, so an IAM failure arrives from cancel_job instead of from
    building the client. Without this it reads as a cancel the scheduler must not retry."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cancel_job.side_effect = RetryableError("Could not get an IAM token")

    with pytest.raises(RunnerError) as exc:
        runner.stop()

    assert type(exc.value) is RunnerRetryableError


def test_stop_reports_a_rejected_api_key_as_permanent():
    """A key IAM refuses is not worth retrying every tick."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.cancel_job.side_effect = RuntimeApiError("IAM rejected the API key (status 403)")

    with pytest.raises(RunnerError) as exc:
        runner.stop()

    assert type(exc.value) is RunnerError


def test_stop_reports_an_unreachable_code_engine_as_retryable():
    """connect() and _get_handler() flatten every IAM failure into RunnerError, which would
    otherwise reach the scheduler as a cancel it should not retry, and never open the breaker."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner._connected = False  # pylint: disable=protected-access
    runner._handler = None  # pylint: disable=protected-access

    with patch(f"{_RUNNER_MOD}.get_ce_auth", side_effect=RunnerError("IAM is down")):
        with pytest.raises(RunnerError) as exc:
            runner.stop()

    assert type(exc.value) is RunnerRetryableError
    mock_handler.cancel_job.assert_not_called()


def test_free_resources_returns_false_without_a_fleet_id():
    runner, mock_handler = _make_runner()

    assert runner.free_resources() is False
    mock_handler.delete_job.assert_not_called()


@pytest.mark.parametrize(
    "status, expected",
    [
        (0, RunnerRetryableError),
        (429, RunnerRetryableError),
        (503, RunnerRetryableError),
        (400, None),
    ],
)
def test_free_resources_raises_the_error_type_for_each_code_engine_status(status, expected):
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.delete_job.side_effect = ApiException(status=status, reason="error")

    if expected is None:
        assert runner.free_resources() is False
    else:
        with pytest.raises(expected):
            runner.free_resources()


@pytest.mark.parametrize(
    "error",
    [
        MaxRetryError(None, "/", reason=NewConnectionError(None, "refused")),
        HttpReadTimeoutError(pool=None, url="/", message="timed out"),
        ProtocolError("connection aborted"),
    ],
)
def test_free_resources_raises_unavailable_when_the_request_failed(error):
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.delete_job.side_effect = error

    with pytest.raises(RunnerRetryableError):
        runner.free_resources()


def test_free_resources_refuses_a_job_that_is_not_terminal():
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner.job.status = Job.RUNNING

    assert runner.free_resources() is False
    mock_handler.delete_job.assert_not_called()


def test_free_resources_warns_when_the_project_did_not_hold_the_fleet():
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.delete_job.return_value = False

    with patch(f"{_RUNNER_MOD}.logger") as mock_logger:
        assert runner.free_resources() is True

    assert mock_logger.warning.called


def test_free_resources_gives_up_when_the_code_engine_host_does_not_resolve():
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.delete_job.side_effect = MaxRetryError(None, "/", reason=NameResolutionError(None, None, None))

    assert runner.free_resources() is False


def test_free_resources_reports_an_iam_failure_as_retryable():
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.delete_job.side_effect = RetryableError("Could not get an IAM token")

    with pytest.raises(RunnerError) as exc:
        runner.free_resources()

    assert type(exc.value) is RunnerRetryableError


def test_free_resources_raises_unavailable_when_the_client_cannot_be_built():
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner._connected = False  # pylint: disable=protected-access

    with patch.object(runner, "connect", side_effect=RunnerError("Unable to connect")):
        with pytest.raises(RunnerRetryableError):
            runner.free_resources()
    mock_handler.delete_job.assert_not_called()


def test_submit_sets_fleet_id_with_cos():
    runner, mock_handler = _make_submit_runner()

    with _patch_settings():
        runner.submit()

    assert runner.job.fleet_id == "fleet-abc"
    mock_handler.submit_job.assert_called_once()


def test_submit_places_the_fleet_on_the_projects_subnet_pool():
    runner, mock_handler = _make_submit_runner()

    with _patch_settings():
        runner.submit()

    placements = mock_handler.submit_job.call_args.kwargs["network_placements"]
    assert placements == [{"type": "subnet_pool", "reference": "subnet-1"}]


def test_submit_gives_the_container_the_functions_identifier_only_for_a_mirrored_job(job_not_mirrored):
    runner, mock_handler = _make_submit_runner()
    with _patch_settings():
        runner.submit()
    names = {e["name"] for e in mock_handler.submit_job.call_args.kwargs["extra_fields"]["run_env_variables"]}
    assert "QISKIT_FUNCTIONS_IDENTIFIER" not in names

    job_not_mirrored.return_value = True
    runner, mock_handler = _make_submit_runner()
    with _patch_settings():
        runner.submit()
    env = {e["name"]: e["value"] for e in mock_handler.submit_job.call_args.kwargs["extra_fields"]["run_env_variables"]}
    assert env["QISKIT_FUNCTIONS_IDENTIFIER"] == str(runner.job.id)


def test_submit_fleet_name_is_vendor_function_and_job_id():
    runner, mock_handler = _make_submit_runner()
    runner.job.id = "1b2c3d4e-0000-4000-8000-000000000001"
    runner.job.program.title = "my-function"
    runner.job.program.provider = MagicMock()
    runner.job.program.provider.name = "ibm"

    with _patch_settings():
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["name"] == "ibm-my-function-1b2c3d4e-0000-4000-8000-000000000001"


def test_submit_fleet_name_is_sanitized_and_bounded_with_custom_vendor():
    runner, mock_handler = _make_submit_runner()
    runner.job.id = "1b2c3d4e-0000-4000-8000-000000000001"
    runner.job.program.title = "My Function! With Spaces And A Very Long Title"
    runner.job.program.provider = None

    with _patch_settings():
        runner.submit()

    name = mock_handler.submit_job.call_args.kwargs["name"]
    assert name == "custom-my-function-1b2c3d4e-0000-4000-8000-000000000001"
    assert len(name) <= 63


def test_submit_adopts_the_fleet_returned_for_a_name_conflict():
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.return_value = {"id": "existing-fleet"}

    with _patch_settings():
        runner.submit()

    assert runner.job.fleet_id == "existing-fleet"


def test_submit_reports_an_iam_failure_as_retryable():
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = RetryableError("Could not get an IAM token")

    with _patch_settings():
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is RunnerRetryableError


def test_submit_fails_a_name_conflict_the_lookup_could_not_resolve():
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = ApiException(status=409, reason="Conflict")
    mock_handler.submit_job.side_effect.body = '{"errors": [{"code": "fleet_resource_name_conflict"}]}'

    with _patch_settings():
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is RunnerError


def test_submit_raises_runner_error_when_cos_not_configured():
    """submit() raises RunnerError when COS is not configured — Fleets requires COS."""
    runner, _ = _make_submit_runner()
    runner._project.cos_bucket_user_data_name = None  # pylint: disable=protected-access
    runner._project.cos_instance_name = None  # pylint: disable=protected-access
    runner._project.cos_key_name = None  # pylint: disable=protected-access

    with _patch_settings(), pytest.raises(RunnerError, match="COS is not configured"):
        runner.submit()


@pytest.mark.parametrize(
    "status, expected",
    [
        (429, RunnerRetryableError),
        (503, RunnerRetryableError),
        (400, RunnerError),
    ],
)
def test_submit_raises_the_error_type_for_each_code_engine_status(status, expected):
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = ApiException(status=status, reason="error")

    with _patch_settings():
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is expected
    mock_handler.submit_job.assert_called_once()


@pytest.mark.parametrize(
    "error, expected",
    [
        (
            ClientError({"Error": {"Code": "SlowDown"}, "ResponseMetadata": {"HTTPStatusCode": 503}}, "PutObject"),
            CosRetryableError,
        ),
        (
            ClientError(
                {"Error": {"Code": "RequestTimeout"}, "ResponseMetadata": {"HTTPStatusCode": 400}}, "PutObject"
            ),
            CosRetryableError,
        ),
        (
            ClientError({"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}}, "PutObject"),
            RunnerError,
        ),
        (
            ClientError(
                {"Error": {"Code": "NotImplemented"}, "ResponseMetadata": {"HTTPStatusCode": 501}}, "PutObject"
            ),
            RunnerError,
        ),
        (CosReadTimeoutError(endpoint_url="https://cos"), CosRetryableError),
        (RetryableError("Code Engine API error: Too Many Requests"), RunnerRetryableError),
    ],
)
def test_submit_raises_the_error_type_for_each_cos_failure(error, expected):
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(), patch.object(runner, "_upload_program_to_cos", side_effect=error):
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is expected
    mock_handler.submit_job.assert_not_called()


@pytest.mark.parametrize(
    "error", [ApiException(status=503, reason="Service Unavailable"), MaxRetryError(None, "/", reason=ProtocolError())]
)
def test_submit_raises_unavailable_when_code_engine_fails_before_the_create(error):
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(), patch.object(runner, "_upload_program_to_cos", side_effect=error):
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is RunnerRetryableError
    mock_handler.submit_job.assert_not_called()


def test_submit_fails_the_job_when_the_code_engine_host_does_not_resolve():
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = MaxRetryError(
        None, "/", reason=NameResolutionError("api.wrong.codeengine.cloud.ibm.com", None, "not found")
    )

    with _patch_settings():
        with pytest.raises(RunnerError) as exc:
            runner.submit()

    assert type(exc.value) is RunnerError


def test_submit_raises_unavailable_when_the_connection_never_opened():
    runner, mock_handler = _make_submit_runner()
    mock_handler.submit_job.side_effect = MaxRetryError(None, "/", reason=NewConnectionError(None, "refused"))

    with _patch_settings():
        with pytest.raises(RunnerRetryableError):
            runner.submit()


def test_submit_raises_runner_error_when_no_fleet_id_returned():
    """submit() raises RunnerError when API returns no fleet ID."""
    runner, mock_handler = _make_submit_runner()
    mock_fleet = MagicMock()
    mock_fleet.to_dict.return_value = {"id": None}
    mock_handler.submit_job.return_value = mock_fleet

    with _patch_settings():
        with pytest.raises(RunnerError, match="fleet ID"):
            runner.submit()


def test_submit_parses_compute_profile_with_gpu():
    """submit() parses compute_profile into cpu, memory, and gpu."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile_id = "gx3d-24x120x1a100p"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "24"
    assert call_kwargs["scale_memory_limit"] == "120G"
    assert call_kwargs["extra_fields"]["scale_gpu"] == {"preferences": [{"family": "a100p", "allocation": "1"}]}


def test_submit_parses_compute_profile_without_prefix():
    """submit() parses profiles without a prefix like '24x120x2a100p'."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile_id = "24x120x2a100p"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "24"
    assert call_kwargs["scale_memory_limit"] == "120G"
    assert call_kwargs["extra_fields"]["scale_gpu"] == {"preferences": [{"family": "a100p", "allocation": "2"}]}


def test_submit_parses_compute_profile_without_gpu():
    """submit() parses a CPU-only profile correctly."""
    runner, mock_handler = _make_submit_runner()
    runner.job.compute_profile_id = "cx3d-4x16"

    with _patch_settings():
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "4"
    assert call_kwargs["scale_memory_limit"] == "16G"
    assert "scale_gpu" not in (call_kwargs.get("extra_fields") or {})


def test_submit_uses_default_profile_when_no_compute_profile():
    """submit() uses DEFAULT_COMPUTE_PROFILE when job has no compute_profile."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(DEFAULT_COMPUTE_PROFILE="cx3d-8x32"):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == "8"
    assert call_kwargs["scale_memory_limit"] == "32G"


def test_submit_default_profile_in_settings_is_parseable():
    """Whatever settings.py defaults DEFAULT_COMPUTE_PROFILE to, the runner parses it.

    Reads the real setting, not a copy, so a changed default cannot leave this passing.
    """
    runner, mock_handler = _make_submit_runner()
    default = django_settings.DEFAULT_COMPUTE_PROFILE
    cpu, memory = normalize_compute_profile(default).split("x")[:2]

    with _patch_settings(DEFAULT_COMPUTE_PROFILE=default):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    assert call_kwargs["scale_cpu_limit"] == cpu
    assert call_kwargs["scale_memory_limit"] == f"{memory}G"
    assert "scale_gpu" not in (call_kwargs.get("extra_fields") or {})


def test_submit_raises_on_unparseable_compute_profile():
    """submit() raises RunnerError when compute_profile cannot be parsed."""
    runner, _ = _make_submit_runner()
    runner.job.compute_profile_id = "not-a-valid-profile"

    with _patch_settings():
        with pytest.raises(RunnerError, match="Could not parse compute_profile"):
            runner.submit()


def test_submit_uses_program_image():
    """submit() uses program.image when set."""
    runner, mock_handler = _make_submit_runner()
    runner.job.program.image = "custom-image:latest"

    with _patch_settings(), patch.object(runner, "_upload_program_to_cos"):
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["image_reference"] == "custom-image:latest"


def test_submit_uses_settings_default_image_when_no_program_image():
    """submit() falls back to FLEETS_DEFAULT_IMAGE when program has no image."""
    runner, mock_handler = _make_submit_runner()

    with _patch_settings(FLEETS_DEFAULT_IMAGE="fallback-image:v2"):
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["image_reference"] == "fallback-image:v2"


def test_submit_uses_default_image_when_artifact_set_even_if_image_also_set():
    """Custom jobs (artifact set) always use FLEETS_DEFAULT_IMAGE, ignoring program.image."""
    runner, mock_handler = _make_submit_runner()
    runner.job.program.artifact = MagicMock()
    runner.job.program.image = "provider-image:latest"

    with _patch_settings(FLEETS_DEFAULT_IMAGE="fleet-node:latest"), patch.object(runner, "_upload_program_to_cos"):
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["image_reference"] == "fleet-node:latest"


def test_submit_uses_config_workers_as_max_instances():
    """submit() uses job.config.workers as scale_max_instances when set."""
    runner, mock_handler = _make_submit_runner()
    runner.job.config = MagicMock()
    runner.job.config.workers = 3

    with _patch_settings():
        runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["scale_max_instances"] == 3


def test_submit_uses_default_max_instances_when_no_config():
    """submit() falls back to 1 when config has no workers."""
    runner, mock_handler = _make_submit_runner()

    runner.submit()

    assert mock_handler.submit_job.call_args.kwargs["scale_max_instances"] == 1


def test_get_result_from_cos_returns_none_when_cos_not_configured():
    """get_result_from_cos() returns None when COS is not configured."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    with patch.object(runner, "_is_cos_configured", return_value=False):
        result = runner.get_result_from_cos()

    assert result is None


def test_get_result_from_cos_returns_json_string():
    """get_result_from_cos() returns decoded results.json from COS."""
    runner, _ = _make_runner(fleet_id="fleet-123")

    runner._cos.get_object_bytes.return_value = b'{"status": "ok"}'  # pylint: disable=protected-access
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    with (
        patch.object(runner, "_is_cos_configured", return_value=True),
        patch.object(runner, "_get_fleet_name", return_value="fleet-name"),
        patch(
            f"{_RUNNER_MOD}.build_job_paths",
            return_value=FleetJobPaths(
                cos_user_function_prefix="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/data",
                cos_user_job_prefix="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca",
                cos_user_log_key="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log",
                cos_results_key="users/IBMid-50FJDA/provider_functions/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/results.json",  # fmt: skip
                cos_provider_function_prefix="providers/Q-CTRL/sampler-v2/data",
                cos_provider_job_prefix="providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca",
                cos_provider_log_key="providers/Q-CTRL/sampler-v2/jobs/8be4df61-93ca/logs.log",
                cos_function_entrypoint="providers/Q-CTRL/sampler-v2/data/main.py",
                cos_docker_entrypoint="providers/Q-CTRL/sampler-v2/data/fleet_provider_job_wrapper.py",
                container_function_entrypoint="/function_provider_data/main.py",
                container_docker_entrypoint="/function_provider_data/fleet_provider_job_wrapper.py",
                container_public_log_path="/job_user_data/logs.log",
                container_private_log_path="/job_provider_data/logs.log",
                container_arguments_path="/job_user_data/arguments.json",
                container_result_path="/job_user_data/results.json",
            ),
        ),
    ):
        result = runner.get_result_from_cos()

    assert result == '{"status": "ok"}'


def test_get_result_from_cos_returns_none_on_exception():
    """get_result_from_cos() returns None when COS retrieval fails."""
    runner, _ = _make_runner(fleet_id="fleet-123")
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._cos.get_object_bytes.side_effect = RuntimeError("COS error")  # pylint: disable=protected-access

    with (
        patch.object(runner, "_is_cos_configured", return_value=True),
        patch.object(runner, "_get_fleet_name", return_value="fleet-name"),
    ):
        result = runner.get_result_from_cos()

    assert result is None


@pytest.mark.parametrize("active,raises", [(True, False), (False, True)])
def test_get_project_existing(active, raises):
    """_get_project() returns an active project; raises if inactive."""
    runner, _ = _make_runner()
    mock_project = MagicMock()
    mock_project.active = active
    mock_project.project_name = "my-project"
    runner.job.program.code_engine_project = mock_project

    if raises:
        with pytest.raises(RunnerError):
            runner._get_project()  # pylint: disable=protected-access
    else:
        assert runner._get_project() is mock_project  # pylint: disable=protected-access


def test_get_project_raises_when_no_project_assigned():
    """_get_project() raises RunnerError when program has no code_engine_project."""
    runner, _ = _make_runner()
    runner.job.program.code_engine_project = None
    runner.job.program.title = "my-program"

    with pytest.raises(RunnerError, match="No Code Engine project assigned"):
        runner._get_project()  # pylint: disable=protected-access


def test_connect_skips_when_already_connected():
    """connect() returns immediately if already connected."""
    runner, mock_handler = _make_runner()
    runner._connected = True  # pylint: disable=protected-access
    runner._handler = mock_handler  # pylint: disable=protected-access

    runner.connect()

    mock_handler.submit_job.assert_not_called()


def test_connect_raises_runner_error_on_failure():
    """connect() raises RunnerError when _get_handler fails."""
    runner, _ = _make_runner()
    runner._connected = False  # pylint: disable=protected-access
    runner._handler = None  # pylint: disable=protected-access

    with patch.object(runner, "_get_handler", side_effect=RuntimeError("connection failed")):
        with pytest.raises(RunnerError, match="connect"):
            runner.connect()


def test_is_cos_configured_true_when_all_fields_set():
    """_is_cos_configured() returns True when all four COS fields are set."""
    runner, _ = _make_runner()
    runner._project.cos_bucket_user_data_name = "u"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "p"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "i"  # pylint: disable=protected-access
    runner._project.cos_key_name = "k"  # pylint: disable=protected-access

    assert runner._is_cos_configured() is True  # pylint: disable=protected-access


def test_is_cos_configured_false_when_project_missing():
    """_is_cos_configured() returns False when _project is None."""
    runner, _ = _make_runner()
    runner._project = None  # pylint: disable=protected-access

    assert runner._is_cos_configured() is False  # pylint: disable=protected-access


def test_get_api_key_returns_from_settings():
    """_get_api_key() returns IBM_CLOUD_API_KEY from settings."""
    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = "my-api-key"
        result = runner._get_api_key()  # pylint: disable=protected-access

    assert result == "my-api-key"


def test_get_api_key_raises_when_not_configured():
    """_get_api_key() raises RunnerError when no API key is configured."""
    runner, _ = _make_runner()

    with patch(f"{_RUNNER_MOD}.settings") as mock_settings:
        mock_settings.IBM_CLOUD_API_KEY = None
        with pytest.raises(RunnerError, match="IBM_CLOUD_API_KEY"):
            runner._get_api_key()  # pylint: disable=protected-access


def test_get_fleet_name_returns_from_api():
    """_get_fleet_name() returns the fleet name from get_job_status."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    mock_handler.get_job_status.return_value = {"name": "job-xyz-123", "status": "running"}

    result = runner._get_fleet_name()  # pylint: disable=protected-access

    assert result == "job-xyz-123"


def test_get_fleet_name_falls_back_on_exception():
    """_get_fleet_name() falls back to job-{id} when API call fails."""
    runner, mock_handler = _make_runner(fleet_id="fleet-123")
    runner.job.id = "job-uuid"
    mock_handler.get_job_status.side_effect = RuntimeError("API error")

    result = runner._get_fleet_name()  # pylint: disable=protected-access

    assert result == "job-job-uuid"


def test_submit_includes_gateway_env_vars():
    """submit() includes decrypted gateway env vars in the run_env_variables."""
    runner, mock_handler = _make_submit_runner()
    runner.job.env_vars = '{"MY_TOKEN": "secret", "MY_URL": "http://example.com"}'
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.program.runner = Program.FLEETS

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    decrypted = {"MY_TOKEN": "decrypted_secret", "MY_URL": "http://example.com"}
    with _patch_settings(), patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value=decrypted):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    env_list = call_kwargs["extra_fields"]["run_env_variables"]
    by_name = {e["name"]: e["value"] for e in env_list}
    assert by_name["MY_TOKEN"] == "decrypted_secret"
    assert by_name["MY_URL"] == "http://example.com"
    assert by_name["ARGUMENTS_PATH"] == "/job_user_data/arguments.json"
    assert by_name["RESULTS_PATH"] == "/job_user_data/results.json"
    assert by_name["PUBLIC_LOG_PATH"] == "/job_user_data/logs.log"


def test_submit_arguments_path_set_exactly_once():
    """submit() sets ARGUMENTS_PATH exactly once even when it appears in job env vars."""
    runner, mock_handler = _make_submit_runner()
    runner.job.env_vars = '{"ARGUMENTS_PATH": "/old/stale/path", "OTHER": "val"}'
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.program.runner = Program.FLEETS

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    decrypted = {"ARGUMENTS_PATH": "/old/stale/path", "OTHER": "val"}
    with _patch_settings(), patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value=decrypted):
        runner.submit()

    call_kwargs = mock_handler.submit_job.call_args.kwargs
    env_list = call_kwargs["extra_fields"]["run_env_variables"]
    arguments_path_entries = [e for e in env_list if e.get("name") == "ARGUMENTS_PATH"]
    assert len(arguments_path_entries) == 1
    assert arguments_path_entries[0]["value"] == "/job_user_data/arguments.json"


def test_upload_provider_image_entrypoint_uploads_to_provider_bucket():
    """_upload_provider_image_entrypoint() uploads rendered template to provider bucket for provider jobs."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = MagicMock()
    runner.job.program.provider.name = "acme"
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.program.runner = Program.FLEETS
    runner.job.id = "job-1"
    runner.job.arguments = "{}"
    runner._project.cos_bucket_provider_data_name = "provider-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access

    paths = build_job_paths(runner.job)

    mock_template = MagicMock()
    mock_template.render.return_value = "rendered content"

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
    ):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access

    call = runner._cos.upload_fileobj.call_args  # pylint: disable=protected-access
    assert call.kwargs["bucket_name"] == "provider-bucket"
    assert call.kwargs["key"] == "providers/acme/my-func/data/main.py"
    assert call.kwargs["fileobj"].read() == b"rendered content"


def test_upload_provider_image_entrypoint_raises_for_non_provider_job():
    """_upload_provider_image_entrypoint() raises RunnerError when called on a non-provider job."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = None
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.id = "job-1"
    runner.job.arguments = "{}"

    paths = build_job_paths(runner.job)

    with pytest.raises(RunnerError, match="non-provider job"):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access


def test_upload_provider_image_entrypoint_error_propagates():
    """_upload_provider_image_entrypoint() does not swallow COS errors."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = MagicMock()
    runner.job.program.provider.name = "acme"
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.program.runner = Program.FLEETS
    runner.job.id = "job-1"
    runner.job.arguments = "{}"
    runner._project.cos_bucket_provider_data_name = "provider-bucket"  # pylint: disable=protected-access

    paths = build_job_paths(runner.job)

    mock_template = MagicMock()
    mock_template.render.return_value = "content"
    runner._cos.upload_fileobj.side_effect = RuntimeError("COS error")  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
        pytest.raises(RuntimeError, match="COS error"),
    ):
        runner._upload_provider_image_entrypoint(paths)  # pylint: disable=protected-access


def test_submit_uses_provider_image_entrypoint_upload_when_image_set():
    """submit() calls _upload_provider_image_entrypoint when program.image is set but no artifact."""
    runner, _ = _make_submit_runner()
    runner.job.program.image = "custom:latest"
    runner.job.program.artifact = None
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.env_vars = "{}"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch.object(runner, "_upload_provider_image_entrypoint") as mock_tmpl,
        patch.object(runner, "_upload_custom_image_entrypoint") as mock_art,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        runner.submit()

    mock_tmpl.assert_called_once()
    mock_art.assert_not_called()


def test_submit_uses_artifact_upload_when_artifact_set():
    """submit() calls _upload_artifact_to_cos (not template) when program.artifact is set."""
    runner, _ = _make_submit_runner()
    runner.job.program.artifact = MagicMock()
    runner.job.program.image = None
    runner.job.author.username = "user-1"
    runner.job.program.provider = None
    runner.job.program.title = "prog"
    runner.job.env_vars = "{}"

    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    runner._project.cos_bucket_provider_data_name = "prov-bucket"  # pylint: disable=protected-access
    runner._project.cos_instance_name = "cos-inst"  # pylint: disable=protected-access
    runner._project.cos_key_name = "cos-key"  # pylint: disable=protected-access
    runner._project.pds_name_users = "pds-users"  # pylint: disable=protected-access
    runner._project.pds_name_providers = "pds-provs"  # pylint: disable=protected-access

    with (
        _patch_settings(),
        patch.object(runner, "_upload_custom_image_entrypoint") as mock_art,
        patch.object(runner, "_upload_provider_image_entrypoint") as mock_tmpl,
        patch(f"{_RUNNER_MOD}.decrypt_env_vars", return_value={}),
    ):
        runner.submit()

    mock_art.assert_called_once()
    mock_tmpl.assert_not_called()


def _build_artifact_tar(members: dict[str, bytes]) -> tarfile.TarFile:
    """Build an in-memory tar and return it opened for reading.

    Args:
        members: Mapping of member name to file content.

    Returns:
        An open ``TarFile`` positioned at the start, ready to iterate.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r")


def _make_custom_artifact_runner() -> tuple[FleetsRunner, FleetJobPaths]:
    """Build a runner and paths wired for _upload_custom_image_entrypoint."""
    runner, _ = _make_runner()
    runner.job.author.username = "alice"
    runner.job.program.provider = None
    runner.job.program.title = "my-func"
    runner.job.program.entrypoint = "main.py"
    runner.job.program.runner = Program.FLEETS
    runner.job.program.artifact = MagicMock()
    runner.job.program.artifact.path = "/tmp/artifact.tar"
    runner.job.id = "job-1"
    runner._project.cos_bucket_user_data_name = "user-bucket"  # pylint: disable=protected-access
    paths = build_job_paths(runner.job)
    return runner, paths


def test_upload_custom_image_entrypoint_skips_traversal_member():
    """_upload_custom_image_entrypoint() skips a member that escapes via ".." and only uploads safe files."""
    runner, paths = _make_custom_artifact_runner()
    tar = _build_artifact_tar({"../evil.txt": b"malicious", "main.py": b"safe"})

    mock_template = MagicMock()
    mock_template.render.return_value = "wrapper"

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
        patch(f"{_RUNNER_MOD}.tarfile.open", return_value=tar),
        patch(f"{_RUNNER_MOD}.logger") as mock_logger,
    ):
        runner._upload_custom_image_entrypoint(paths)  # pylint: disable=protected-access

    uploaded_keys = [
        call.kwargs["key"] for call in runner._cos.upload_fileobj.call_args_list  # pylint: disable=protected-access
    ]
    # The safe member is uploaded under the job's function prefix.
    assert f"{paths.cos_user_function_prefix}/main.py" in uploaded_keys
    # No uploaded key references the traversal member.
    assert not any("evil.txt" in key for key in uploaded_keys)
    # The unsafe member is logged as skipped.
    mock_logger.warning.assert_called_once()
    assert "../evil.txt" in mock_logger.warning.call_args.args


def test_upload_custom_image_entrypoint_skips_absolute_member():
    """_upload_custom_image_entrypoint() skips an absolute-path member and only uploads safe files."""
    runner, paths = _make_custom_artifact_runner()
    tar = _build_artifact_tar({"/abs/evil.txt": b"malicious", "main.py": b"safe"})

    mock_template = MagicMock()
    mock_template.render.return_value = "wrapper"

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
        patch(f"{_RUNNER_MOD}.tarfile.open", return_value=tar),
        patch(f"{_RUNNER_MOD}.logger") as mock_logger,
    ):
        runner._upload_custom_image_entrypoint(paths)  # pylint: disable=protected-access

    uploaded_keys = [
        call.kwargs["key"] for call in runner._cos.upload_fileobj.call_args_list  # pylint: disable=protected-access
    ]
    assert f"{paths.cos_user_function_prefix}/main.py" in uploaded_keys
    assert not any("evil.txt" in key for key in uploaded_keys)
    mock_logger.warning.assert_called_once()


def test_upload_custom_image_entrypoint_keeps_dotdot_prefixed_name():
    """_upload_custom_image_entrypoint() uploads a legit name like "..config" that is not real traversal."""
    runner, paths = _make_custom_artifact_runner()
    tar = _build_artifact_tar({"..config": b"data", "main.py": b"safe"})

    mock_template = MagicMock()
    mock_template.render.return_value = "wrapper"

    with (
        _patch_settings(),
        patch(f"{_RUNNER_MOD}.get_template", return_value=mock_template),
        patch(f"{_RUNNER_MOD}.tarfile.open", return_value=tar),
        patch(f"{_RUNNER_MOD}.logger") as mock_logger,
    ):
        runner._upload_custom_image_entrypoint(paths)  # pylint: disable=protected-access

    uploaded_keys = [
        call.kwargs["key"] for call in runner._cos.upload_fileobj.call_args_list  # pylint: disable=protected-access
    ]
    assert f"{paths.cos_user_function_prefix}/..config" in uploaded_keys
    assert f"{paths.cos_user_function_prefix}/main.py" in uploaded_keys
    mock_logger.warning.assert_not_called()


_TASKS = "ce/test-project-id/fleet-123/v3/tasks/"
_TASK_FILE = f"{_TASKS}00000000-0000-0000-0000-000000000001"


def _task_file(started_at="2026-01-02T03:04:05.123456789Z", finished_at="2026-01-02T03:06:07.5Z", **extra):
    """The task file Code Engine keeps, with invented values and only the keys the gateway reads or must ignore."""
    lines = ["taskState: successful", "status:", "- worker: fleet-test-0", "  startTime: '2000-01-01T00:00:00Z'"]
    lines += ["  endTime: '2000-01-01T00:00:09Z'"]
    for key, value in {"startedAt": started_at, "finishedAt": finished_at, **extra}.items():
        lines.append(f"{key}: {value}")
    return ("\n".join(lines) + "\n").encode()


def _listing(*keys):
    return [{"key": key, "size": 100, "last_modified": None} for key in keys]


class TestTaskTimes:
    """get_task_times() reads when Code Engine says the task started and finished, and never raises."""

    _NOW = datetime.now(timezone.utc).replace(microsecond=0)
    _CREATED = _NOW - timedelta(minutes=10)
    _STARTED = _NOW - timedelta(minutes=5)
    _FINISHED = _NOW - timedelta(minutes=2)

    @staticmethod
    def _iso(moment):
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _file(self, started_at=None, finished_at=None):
        return _task_file(
            started_at=self._iso(self._STARTED) if started_at is None else started_at,
            finished_at=self._iso(self._FINISHED) if finished_at is None else finished_at,
        )

    def _runner(self, content=None, listing=None):
        runner, _ = _make_runner(fleet_id="fleet-123")
        cos = runner._cos  # pylint: disable=protected-access
        cos.list_with_metadata.return_value = _listing(_TASK_FILE) if listing is None else listing
        cos.get_object_bytes.return_value = self._file() if content is None else content
        return runner

    def test_they_are_startedat_and_finishedat(self):
        times = self._runner().get_task_times()

        assert times.started_at == self._STARTED
        assert times.finished_at == self._FINISHED

    def test_they_are_timezone_aware(self):
        times = self._runner().get_task_times()

        assert times.started_at.utcoffset() == timedelta(0)
        assert times.finished_at.utcoffset() == timedelta(0)

    def test_the_times_of_the_worker_are_not_read(self):
        """startTime and endTime under status are the worker's, and are not the ones billed."""
        times = self._runner(_task_file(started_at="null", finished_at="null")).get_task_times()

        assert times == (None, None)

    def test_quoted_times_are_read_too(self):
        content = self._file(started_at=f"'{self._iso(self._STARTED)}'", finished_at=f"'{self._iso(self._FINISHED)}'")

        times = self._runner(content).get_task_times()

        assert times == (self._STARTED, self._FINISHED)

    def test_a_task_that_has_not_finished_has_only_the_start(self):
        times = self._runner(self._file(finished_at="null")).get_task_times()

        assert times.started_at == self._STARTED
        assert times.finished_at is None

    def test_the_zero_time_code_engine_writes_while_the_task_runs_is_none(self, caplog):
        """finishedAt is there before the task finishes, with the zero time of Go: year 1."""
        content = self._file(finished_at="0001-01-01T00:00:00Z")

        times = self._runner(content).get_task_times()

        assert times == (self._STARTED, None)
        assert "finishedAt" in caplog.text

    def test_a_missing_key_is_none(self):
        content = b"taskState: pending\n"

        assert self._runner(content).get_task_times() == (None, None)

    @pytest.mark.parametrize("value", ["not-a-date", "2026-01-02T03:04:05", "'2026-01-02T03:04:05'", "12", "[1, 2]"])
    def test_a_value_that_is_not_a_timestamp_with_timezone_is_none(self, value, caplog):
        """A time without timezone cannot be compared with the aware ones downstream."""
        times = self._runner(self._file(started_at=value)).get_task_times()

        assert times.started_at is None
        assert times.finished_at == self._FINISHED
        assert "startedAt that is not a timestamp" in caplog.text

    @pytest.mark.parametrize("content", [b"", b"- a\n- b\n", b"just text", b"{unclosed: ["])
    def test_a_file_that_is_not_a_yaml_mapping_gives_no_times(self, content):
        assert self._runner(content).get_task_times() == (None, None)

    def test_the_content_is_never_logged(self, caplog):
        """The file holds tokens, and a YAML error quotes the line it failed on."""
        self._runner(b"env: {ENV_JOB_GATEWAY_TOKEN: secret-token-value, : [}\n").get_task_times()

        assert "secret-token-value" not in caplog.text
        assert "is not valid YAML" in caplog.text

    def test_it_reads_the_only_file_under_the_tasks_prefix(self):
        runner = self._runner()

        runner.get_task_times()

        cos = runner._cos  # pylint: disable=protected-access
        cos.list_with_metadata.assert_called_once_with(bucket_name="task-store-bucket", prefix=_TASKS)
        cos.get_object_bytes.assert_called_once_with(bucket_name="task-store-bucket", key=_TASK_FILE)

    def test_a_directory_marker_is_not_a_task_file(self):
        runner = self._runner(listing=_listing(_TASKS, _TASK_FILE))

        assert runner.get_task_times().started_at == self._STARTED
        runner._cos.get_object_bytes.assert_called_once()  # pylint: disable=protected-access

    def test_no_file_yet_gives_no_times(self):
        runner = self._runner(listing=[])

        assert runner.get_task_times() == (None, None)
        runner._cos.get_object_bytes.assert_not_called()  # pylint: disable=protected-access

    def test_only_the_current_layout_is_read(self):
        runner = self._runner()

        runner.get_task_times()

        prefixes = [
            call.kwargs["prefix"] for call in runner._cos.list_with_metadata.call_args_list
        ]  # pylint: disable=protected-access
        assert prefixes == [_TASKS]

    def test_it_is_none_without_a_fleet(self):
        runner, _ = _make_runner(fleet_id=None)

        assert runner.get_task_times() == (None, None)
        runner._cos.list_with_metadata.assert_not_called()  # pylint: disable=protected-access

    def test_it_is_none_when_the_task_store_bucket_is_not_configured(self):
        runner = self._runner()
        runner._project.cos_bucket_task_store_name = None  # pylint: disable=protected-access

        assert runner.get_task_times() == (None, None)

    def test_a_listing_error_gives_no_times_instead_of_raising(self, caplog):
        runner = self._runner()
        runner._cos.list_with_metadata.side_effect = ClientError(  # pylint: disable=protected-access
            {"Error": {"Code": "AccessDenied"}}, "ListObjectsV2"
        )

        assert runner.get_task_times() == (None, None)
        assert "COS listing failed" in caplog.text

    def test_an_error_reading_the_file_gives_no_times_instead_of_raising(self, caplog):
        runner = self._runner()
        runner._cos.get_object_bytes.side_effect = RuntimeError("boom")  # pylint: disable=protected-access

        assert runner.get_task_times() == (None, None)
        assert "Could not read the task times" in caplog.text


@pytest.mark.django_db
class TestExecutionProject:
    """The fleet lives in the project the job ran in, which the program may no longer point at."""

    @staticmethod
    def _job(program, **kwargs):
        return TestUtils.create_job(
            author=program.author,
            program=program,
            status=Job.SUCCEEDED,
            runner=Program.FLEETS,
            fleet_id="fleet-123",
            **kwargs,
        )

    @staticmethod
    def _program(project):
        return TestUtils.create_program(
            program_title="a-function", author="owner", runner=Program.FLEETS, code_engine_project=project
        )

    def test_falls_back_to_the_program_without_a_snapshot(self):
        project = TestUtils.get_or_create_ce_project(
            project_name="only-project", project_id="only-id", cos_bucket_user_data_name="b3"
        )
        job = self._job(self._program(project), ce_project_name=None)

        resolved = FleetsRunner(job)._execution_project()  # pylint: disable=protected-access

        assert resolved.project_id == "only-id"

    def test_resolves_an_inactive_project(self):
        TestUtils.get_or_create_ce_project(
            project_name="gone-project", project_id="gone-id", cos_bucket_user_data_name="b4", active=False
        )
        still_active = TestUtils.get_or_create_ce_project(
            project_name="live-project", project_id="live-id", cos_bucket_user_data_name="b6"
        )
        job = self._job(self._program(still_active), ce_project_name="gone-project")

        resolved = FleetsRunner(job)._execution_project()  # pylint: disable=protected-access

        assert resolved.project_id == "gone-id"

    def test_free_resources_sends_the_delete_to_the_project_the_job_ran_in(self):
        TestUtils.get_or_create_ce_project(
            project_name="old-project", project_id="old-id", cos_bucket_user_data_name="b1", region="us-east"
        )
        moved_to = TestUtils.get_or_create_ce_project(
            project_name="new-project", project_id="new-id", cos_bucket_user_data_name="b2", region="eu-de"
        )
        job = self._job(self._program(moved_to), ce_project_name="old-project", ce_region="us-east")

        with (
            patch(f"{_RUNNER_MOD}.get_ce_auth") as get_ce_auth,
            patch(f"{_RUNNER_MOD}.FleetHandler") as handler_cls,
            patch.object(FleetsRunner, "_get_api_key", return_value="an-api-key"),
        ):
            assert FleetsRunner(job).free_resources() is True

        assert get_ce_auth.call_args.args[1] == "us-east"
        assert handler_cls.call_args.kwargs["project_id"] == "old-id"
        handler_cls.return_value.delete_job.assert_called_once_with("fleet-123")

    @staticmethod
    def _duplicate_of(project, *, project_id, **kwargs):
        """A second row with the same project_name. TestUtils gets-or-creates by name, so it cannot."""
        fields = {
            field.name: getattr(project, field.name)
            for field in CodeEngineProject._meta.fields  # pylint: disable=protected-access
            if field.name not in ("id", "created", "updated")
        }
        return CodeEngineProject.objects.create(**{**fields, "project_id": project_id, **kwargs})

    def test_prefers_the_active_project_when_two_share_a_name(self):
        dead = TestUtils.get_or_create_ce_project(
            project_name="twice", project_id="dead-id", cos_bucket_user_data_name="b7", active=False
        )
        alive = self._duplicate_of(dead, project_id="alive-id", active=True)
        job = self._job(self._program(alive), ce_project_name="twice")

        resolved = FleetsRunner(job)._execution_project()  # pylint: disable=protected-access

        assert resolved.project_id == "alive-id"

    def test_narrows_by_region_when_two_projects_share_a_name(self):
        in_us = TestUtils.get_or_create_ce_project(
            project_name="shared", project_id="us-id", cos_bucket_user_data_name="b8", region="us-east"
        )
        self._duplicate_of(in_us, project_id="eu-id", region="eu-de")
        job = self._job(self._program(in_us), ce_project_name="shared", ce_region="eu-de")

        resolved = FleetsRunner(job)._execution_project()  # pylint: disable=protected-access

        assert resolved.project_id == "eu-id"

    def test_free_resources_sends_nothing_for_an_unknown_project(self):
        project = TestUtils.get_or_create_ce_project(
            project_name="known", project_id="known-id", cos_bucket_user_data_name="b5"
        )
        job = self._job(self._program(project), ce_project_name="vanished-project")
        runner = FleetsRunner(job)

        with patch.object(runner, "connect") as connect:
            assert runner.free_resources() is False
        connect.assert_not_called()
