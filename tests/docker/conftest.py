# pylint: disable=import-error, invalid-name
"""Fixtures for tests"""
import os

from pytest import fixture
from testcontainers.compose import DockerCompose
from qiskit_serverless import ServerlessClient, QiskitFunction
from qiskit_serverless.core.clients.local_client import LocalClient

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)

_compose_instance = None


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


def set_up_serverless_client():
    """Auxiliar fixture function to create a serverless client"""
    global _compose_instance

    compose = DockerCompose(
        resources_path,
        compose_file_name="../../../docker-compose-dev.yaml",
        pull=False,
    )
    compose.start()
    _compose_instance = compose

    connection_url = "http://localhost:8000"
    compose.wait_for(f"{connection_url}/backoffice")

    serverless = ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", connection_url),
        instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
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


def print_container_logs(test_name, container_name, num_lines=100):
    """Print logs from a specific container."""
    global _compose_instance
    import traceback

    if _compose_instance is None:
        print(f"WARNING: No compose instance available for {container_name} logs")
        return

    try:
        print(f"\n--- {test_name}: {container_name} logs (last {num_lines} lines) ---")
        logs = _compose_instance.get_logs(container_name)

        log_text = logs[0] if logs[0] else logs[1]

        lines = log_text.split("\n")
        for line in lines[-num_lines:]:
            print(line)
    except Exception as e:
        print(f"Failed to get {container_name} logs: {e}")
        traceback.print_exc()


@fixture(autouse=True)
def log_test_failures(request):
    """Fixture to print container logs if a test fail"""
    initial_failures = request.session.testsfailed

    yield  # Run the test...

    if request.session.testsfailed > initial_failures:
        print_container_logs(request.node.name, "gateway")
        print_container_logs(request.node.name, "scheduler")

        print("=" * 80 + "\n")
