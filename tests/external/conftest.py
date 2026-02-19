# pylint: disable=import-error, invalid-name
"""Fixtures for external runtime tests."""

import os

from pytest import fixture
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_serverless import ServerlessClient

REQUIRED_QISKIT_VARS = ["QISKIT_IBM_TOKEN", "QISKIT_IBM_INSTANCE", "QISKIT_IBM_URL"]
missing_vars = [var for var in REQUIRED_QISKIT_VARS if var not in os.environ]
if missing_vars:
    raise EnvironmentError(
        f"Missing required environment variables: {', '.join(missing_vars)}. "
        "Please set these variables before running external tests."
    )

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")
QISKIT_IBM_TOKEN = os.environ["QISKIT_IBM_TOKEN"]
QISKIT_IBM_INSTANCE = os.environ["QISKIT_IBM_INSTANCE"]
QISKIT_IBM_URL = os.environ["QISKIT_IBM_URL"]
QISKIT_IBM_CHANNEL = os.environ.get("QISKIT_IBM_CHANNEL", "ibm_quantum_platform")

print(f"- GATEWAY_TOKEN: {GATEWAY_TOKEN[:4]}****")
print(f"- GATEWAY_HOST: {GATEWAY_HOST}")
print(f"- GATEWAY_INSTANCE: {GATEWAY_INSTANCE}")
print(f"- GATEWAY_CHANNEL: {GATEWAY_CHANNEL}")
print(f"- QISKIT_IBM_TOKEN: {QISKIT_IBM_TOKEN[:4]}****")
print(f"- QISKIT_IBM_INSTANCE: {QISKIT_IBM_INSTANCE}")
print(f"- QISKIT_IBM_URL: {QISKIT_IBM_URL}")
print(f"- QISKIT_IBM_CHANNEL: {QISKIT_IBM_CHANNEL}")


@fixture(scope="session")
def serverless_client():
    """Fixture for testing files with serverless client."""
    return ServerlessClient(
        token=GATEWAY_TOKEN,
        host=GATEWAY_HOST,
        instance=GATEWAY_INSTANCE,
        channel=GATEWAY_CHANNEL,
    )


@fixture(scope="session")
def selected_backends():
    """Fixture that returns exactly 2 operational test backends."""
    service = QiskitRuntimeService(
        token=QISKIT_IBM_TOKEN,
        instance=QISKIT_IBM_INSTANCE,
        url=QISKIT_IBM_URL,
        channel=QISKIT_IBM_CHANNEL,
    )
    all_backends = service.backends()
    print(f"Getting backends from {QISKIT_IBM_URL}:", [b.name for b in all_backends])

    backends = []
    for backend in all_backends:
        if not backend.name.startswith("test_"):
            continue
        status = backend.status()
        if not (status.operational and status.status_msg in ("active", "", None)):
            continue

        try:
            backend.properties()
            backends.append(backend.name)
            print(
                f"   Checking {backend.name}... operational={status.operational} "
                f"status_msg={status.status_msg} jobs={status.pending_jobs} -> OK"
            )
            if len(backends) == 2:
                break
        except Exception as e:  # pylint: disable=broad-exception-caught
            # properties() could fail with '404 Client Error: Not Found for url:
            # https://.../api/v1/backends/test_heron_pok003/properties
            # Since properties() is called during session creation, this code ensures
            # the session test won't fail
            print(
                f"   [ERROR] Checking {backend.name}... operational={status.operational} "
                f"status_msg={status.status_msg} -> FAILED: {e}"
            )
            continue

    print("Selected backends:", backends)

    if len(backends) < 2:
        raise RuntimeError(
            f"Expected 2 operational test backends, but found only {len(backends)}: "
            f"{backends}. Tests require at least 2 backends with names starting with "
            "'test_' that are operational and have status 'active', '' or None."
        )
    return backends
