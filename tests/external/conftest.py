# pylint: disable=R0801,import-error, invalid-name
"""Fixtures and minimal runtime patches for external tests."""

import os
from urllib.parse import urlparse

from pytest import fixture
import qiskit_ibm_runtime
from qiskit_serverless.serializers import program_serializers
from qiskit_serverless.core.clients.serverless_client import (
    ServerlessClient as _ServerlessClientInternal,
)
from qiskit_serverless import ServerlessClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")

print("GATEWAY_HOST:", GATEWAY_HOST)
print("GATEWAY_TOKEN:", GATEWAY_TOKEN[:6] + "***********")
print("GATEWAY_INSTANCE:", GATEWAY_INSTANCE)
print("GATEWAY_CHANNEL:", GATEWAY_CHANNEL)


def _is_mock_runtime_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme == "mock":
        return True
    return "mock-runtime" in url


def pytest_configure():
    """Patch only what is needed for mock runtime URLs."""

    _original_qiskit_runtime_service = qiskit_ibm_runtime.QiskitRuntimeService
    _original_stop = _ServerlessClientInternal.stop
    _original_status = _ServerlessClientInternal.status
    _mock_stopped_jobs = set()

    class _PatchedQiskitRuntimeService:
        """Patched QiskitRuntimeService for mocking purposes."""

        def __init__(self, *args, **kwargs):
            """Initializes the patched QiskitRuntimeService."""
            runtime_url = kwargs.get("url") or os.environ.get("QISKIT_IBM_URL", "")
            self._is_mock = _is_mock_runtime_url(runtime_url)
            if self._is_mock:
                self._account = {
                    "channel": kwargs.get("channel"),
                    "token": kwargs.get("token"),
                    "instance": kwargs.get("instance"),
                    "url": runtime_url,
                }
            else:
                self._service = _original_qiskit_runtime_service(*args, **kwargs)

        def active_account(self):
            """Returns the active account."""
            if self._is_mock:
                return self._account
            return self._service.active_account()

        def __getattr__(self, attr):
            if self._is_mock:
                raise AttributeError(attr)
            return getattr(self._service, attr)

    # Used by test module imports and by serializers isinstance checks.
    qiskit_ibm_runtime.QiskitRuntimeService = _PatchedQiskitRuntimeService
    program_serializers.QiskitRuntimeService = _PatchedQiskitRuntimeService

    def _patched_stop(self, job_id: str, service=None):
        runtime_url = os.environ.get("QISKIT_IBM_URL", "")
        if _is_mock_runtime_url(runtime_url):
            _mock_stopped_jobs.add(job_id)
            return "Job has been stopped. Canceled runtime session"
        return _original_stop(self, job_id, service=service)

    def _patched_status(self, job_id: str):
        runtime_url = os.environ.get("QISKIT_IBM_URL", "")
        if _is_mock_runtime_url(runtime_url) and job_id in _mock_stopped_jobs:
            return "STOPPED"
        return _original_status(self, job_id)

    _ServerlessClientInternal.stop = _patched_stop
    _ServerlessClientInternal.status = _patched_status


@fixture(scope="session")
def serverless_client():
    """Fixture for external tests with serverless client."""
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=GATEWAY_INSTANCE,
        channel=GATEWAY_CHANNEL,
    )
