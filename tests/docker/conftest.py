# pylint: disable=import-error, invalid-name
""" Fixtures for tests """
import os
from subprocess import CalledProcessError

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


def set_up_serverless_client(compose_file_name="../../../docker-compose-dev.yaml", backoffice_port=8000):
    """Auxiliar fixture function to create a serverless client"""
    compose = DockerCompose(
        resources_path,
        compose_file_name=compose_file_name,
        pull=False
    )
    try:
      compose.start()
    except CalledProcessError as error:
        print("COMPOSE START ERROR")
        print("STDOUT:")
        print(error.stdout)
        print("STDERR:")
        print(error.stderr)
        raise error

    print(f"Docker started... (compose file: ${compose_file_name})")
    connection_url = f"http://localhost:{backoffice_port}"
    compose.wait_for(f"{connection_url}/backoffice")
    print(f"backoffice ready... (port: ${backoffice_port})")

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", connection_url),
    )
    print("ServerlessClient verified...")

    # Initialize serverless folder for current user
    function = QiskitFunction(
        title="hello-world",
        entrypoint="hello_world.py",
        working_dir=resources_path,
    )
    serverless.upload(function)
    print("ServerlessClient ready...")

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
        compose_file_name="../docker-compose-test.yaml",
        backoffice_port=8001
    )

    yield serverless

    compose.stop()
