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
def base_client(request):
    """Fixture for testing files with every client."""
    if request.param == "serverless":
        [compose, serverless] = set_up_serverless_client()
        yield serverless
        compose.stop()
    else:
        yield LocalClient()


@fixture(scope="module")
def local_client():
    """Fixture for testing files with local client."""
    return LocalClient()


def set_up_serverless_client(compose_file_name="../../../docker-compose-dev.yaml"):
    """Auxiliar fixture function to create a serverless client"""
    compose = DockerCompose(
        resources_path,
        compose_file_name=compose_file_name,
        pull=False,
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

    return [compose, serverless]


@fixture(scope="module")
def serverless_client():
    """Fixture for testing files with serverless client."""
    [compose, serverless] = set_up_serverless_client()

    yield serverless

    compose.stop()


@fixture(scope="module")
def serverless_custom_image_yaml_client():
    """Fixture for testing files with serverless client."""
    [compose, serverless] = set_up_serverless_client(
        compose_file_name="../docker-compose-test.yaml"
    )

    yield serverless

    compose.stop()
