# pylint: disable=import-error, invalid-name, line-too-long, redefined-outer-name
"""Fixtures for instance permission tests."""

import os

from pytest import fixture
from qiskit_serverless import QiskitFunction, ServerlessClient

GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
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
def other_function_title():
    """Title of a second function that exists in the DB but is NOT in any test CRN's entitlements.

    This function must be pre-seeded in the test environment (e.g. via the gateway admin panel
    or a management command) and must NOT appear in any of the four test CRN entitlements.
    Override with TEST_OTHER_FUNCTION_TITLE env var.
    """
    return os.environ.get("TEST_OTHER_FUNCTION_TITLE", "instances2-test")


@fixture(scope="session")
def seeded_job_id(combined_client, provider_name, function_title, tmp_path_factory):
    """Ensure at least one known job exists for the test function at session start.

    Uploads the function (idempotent) and runs a job using combined_client, which has all
    required permissions. Returns the job_id so tests can reference a known job without
    relying on pre-existing environment state.
    """
    tmp = tmp_path_factory.mktemp("job_seed")
    (tmp / "main.py").write_text('print("seeded job")\n')
    fn = QiskitFunction(
        title=function_title,
        provider=provider_name,
        entrypoint="main.py",
        working_dir=str(tmp),
    )
    combined_client.upload(fn)
    job = combined_client.run(function_title, provider=provider_name)
    return job.job_id


@fixture(scope="session")
def none_client():
    """Client authenticated with an instance that has no permissions (empty functions list).
    Permissions: (none)
    """
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=os.environ.get(
            "TEST_NONE_INSTANCE",
            "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:f0e2a145-2282-4605-9f54-eafdb7ec68a1::",
        ),
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def user_client():
    """Client authenticated with a user permissions instance.
    Permissions: function.read, function.run, function-files.read, function-files.write
    """
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=os.environ.get(
            "TEST_USER_INSTANCE",
            "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:6f3d655d-796c-43b9-9d03-a765ab3f6f62::",
        ),
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def provider_client():
    """Client authenticated with a provider permissions instance.
    Permissions: function.write, function-job.read, function-provider-logs.read,
                 function-provider-files.read, function-provider-files.write
    """
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=os.environ.get(
            "TEST_PROVIDER_INSTANCE",
            "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:aad85243-d34e-4374-b22a-ba59fa11e12f::",
        ),
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def combined_client():
    """Client authenticated with all permissions instance.
    Permissions: function.read, function.run, function-files.read, function-files.write,
                 function.write, function-job.read, function-provider-logs.read,
                 function-provider-files.read, function-provider-files.write
    """
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=os.environ.get(
            "TEST_ALL_INSTANCE",
            "crn:v1:staging:public:quantum-computing:us-east:a/efb0dd39cdb64955b8f6e32d44290acf:e862a3cb-ff3b-49c7-9d80-20be5656e550::",
        ),
        channel=GATEWAY_CHANNEL,
    )
