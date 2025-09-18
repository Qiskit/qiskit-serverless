# pylint: disable=import-error, invalid-name
""" Fixtures for tests """
import os

from pytest import fixture
from qiskit_serverless import ServerlessClient

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


@fixture(scope="module")
def staging_client():
    """Fixture for testing files with serverless client."""
    serverless = ServerlessClient(
        name="staging-client",
        host="https://qiskit-serverless-dev.quantum.ibm.com",
        channel="ibm_quantum_platform",
        token=os.environ["QISKIT_IBM_TOKEN"],
        instance=os.environ["QISKIT_IBM_INSTANCE"],
    )
    yield serverless