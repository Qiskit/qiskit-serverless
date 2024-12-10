# pylint: disable=import-error, invalid-name
""" Fixtures for tests """
import os

from pytest import fixture
from testcontainers.compose import DockerCompose
from qiskit_serverless import ServerlessClient, QiskitFunction
from qiskit_serverless.core.clients.local_client import LocalClient

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


@fixture(scope="module", params=["serverless", "local"])
def any_client(request):
    """Fixture for testing files with every client."""
    if request.param == "serverless":
        yield serverless_client()
        return serverless_client()

    return local_client()


@fixture(scope="module")
def local_client():
    """Fixture for testing files with local client."""
    return LocalClient()


@fixture(scope="module")
def serverless_client():
    """Fixture for testing files with serverless client."""
    compose = DockerCompose(
        resources_path,
        compose_file_name="../../../docker-compose-dev.yaml",
        pull=True,
    )
    compose.start()

    connection_url = "http://localhost:8000"
    compose.wait_for(f"{connection_url}/backoffice")

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", connection_url),
    )

    # Initialize serverless folder for current user
    function = QiskitFunction(
        title="hello-world",
        entrypoint="hello_world.py",
        working_dir=resources_path,
    )
    serverless.upload(function)

    yield serverless

    compose.stop()
