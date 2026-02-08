# pylint: disable=import-error, invalid-name
"""Fixtures for tests.

This module provides pytest fixtures for integration tests.
It assumes the server is pre-started externally (via docker-compose or kubernetes).
"""

import os

from pytest import fixture
from qiskit_serverless import ServerlessClient, QiskitFunction


def create_serverless_client():
    """Create a serverless client connected to a pre-started server."""
    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://127.0.0.1:8000"),
        instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
    )
    return serverless


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return create_serverless_client()
