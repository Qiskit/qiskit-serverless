# pylint: disable=import-error, invalid-name
"""Fixtures for tests.

This module provides pytest fixtures for integration tests.
It assumes the server is pre-started externally (via docker-compose or kubernetes).
"""

import os

from pytest import fixture
from qiskit_serverless import ServerlessClient, QiskitFunction

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)

# Cached client instance for session scope
_client_instance = None


def create_serverless_client():
    """Create a serverless client connected to a pre-started server."""
    global _client_instance  # pylint: disable=global-statement

    if _client_instance is not None:
        return _client_instance

    connection_url = os.environ.get("GATEWAY_HOST", "http://localhost:80")

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=connection_url,
        instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
    )

    # Initialize serverless folder for current user
    function = QiskitFunction(
        title="hello-world",
        entrypoint="hello_world.py",
        working_dir=resources_path,
    )
    serverless.upload(function)

    _client_instance = serverless
    return serverless


@fixture(scope="session")
def base_client():
    """Fixture for testing files with every client."""
    return create_serverless_client()


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return create_serverless_client()
