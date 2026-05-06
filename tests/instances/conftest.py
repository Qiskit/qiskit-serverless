# pylint: disable=import-error, invalid-name
"""Fixtures for instance permission tests."""

import os

from pytest import fixture
from qiskit_serverless import ServerlessClient

GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")

PROVIDER_NAME = os.environ.get("TEST_PROVIDER_NAME", "ibm-dev")
FUNCTION_TITLE = os.environ.get("TEST_FUNCTION_TITLE", "instances1-test")


@fixture(scope="session")
def provider_name():
    """Provider name of the test function."""
    return PROVIDER_NAME


@fixture(scope="session")
def function_title():
    """Title of the test function."""
    return FUNCTION_TITLE


@fixture(scope="session")
def user_client():
    """Client authenticated with a user permissions instance.
    Default CRN: test-crn-user
    Permissions: function.read, function.run, function.job.read, function.files
    """
    return ServerlessClient(
        token=os.environ.get("TEST_USER_TOKEN", "awesome_token"),
        host=GATEWAY_HOST,
        instance=os.environ.get("TEST_USER_INSTANCE", "test-crn-user"),
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def provider_client():
    """Client authenticated with a provider permissions instance.
    Default CRN: test-crn-provider
    Permissions: function.provider.upload, function.provider.jobs, function.provider.logs, function.provider.files
    """
    return ServerlessClient(
        token=os.environ.get("TEST_PROVIDER_TOKEN", "awesome_token"),
        host=GATEWAY_HOST,
        instance=os.environ.get("TEST_PROVIDER_INSTANCE", "test-crn-provider"),
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def combined_client():
    """Client authenticated with all permissions instance.
    Default CRN: test-crn-all
    Permissions: function.read, function.run, function.job.read, function.files
                 function.provider.upload, function.provider.jobs, function.provider.logs, function.provider.files
    """
    return ServerlessClient(
        token=os.environ.get("TEST_ALL_TOKEN", "awesome_token"),
        host=GATEWAY_HOST,
        instance=os.environ.get("TEST_ALL_INSTANCE", "test-crn-all"),
        channel=GATEWAY_CHANNEL,
    )
