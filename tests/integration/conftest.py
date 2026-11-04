# pylint: disable=import-error, invalid-name
"""Fixtures for tests.

This module provides pytest fixtures for integration tests.
It assumes the server is pre-started externally (via docker-compose or kubernetes).
"""

import os

from pytest import fixture
from qiskit_serverless import QiskitFunction, ServerlessClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")


@fixture(autouse=True)
def _default_runner_ray(monkeypatch):
    """Pin the client's default runner to Ray for this suite.

    These integration tests run against the docker-compose-dev / Ray gateway,
    which has no Code Engine project, so every function here must run on Ray.
    ``QiskitFunction.runner`` now defaults to ``"fleets"``, and the tests upload
    without naming a runner, so without this they would be submitted as Fleets
    functions and the gateway would 500. Swap the dataclass default back to Ray
    for the suite instead of adding ``runner="ray"`` to every call site.
    """
    defaults = QiskitFunction.__init__.__defaults__
    patched = tuple("ray" if value == "fleets" else value for value in defaults)
    monkeypatch.setattr(QiskitFunction.__init__, "__defaults__", patched)


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=GATEWAY_INSTANCE,
        channel=GATEWAY_CHANNEL,
    )
