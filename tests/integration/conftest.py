# pylint: disable=import-error, invalid-name
"""Fixtures for tests.

This module provides pytest fixtures for integration tests.
It assumes the server is pre-started externally (via docker-compose or kubernetes).
"""

import os

from pytest import fixture
from qiskit_serverless import ServerlessClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=GATEWAY_INSTANCE,
        channel=GATEWAY_CHANNEL,
    )
