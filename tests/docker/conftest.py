# pylint: disable=import-error, invalid-name
"""Fixtures for tests"""
import os
from datetime import datetime

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


def set_up_serverless_client():
    """Auxiliar fixture function to create a serverless client"""
    compose = DockerCompose(
        resources_path,
        compose_file_name="../../../docker-compose-dev.yaml",
        pull=False,
    )
    compose.start()

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

    # keep docker logs
    compose_logs = compose.get_logs()[0]
    lines = [line for line in compose_logs.splitlines() if line.startswith("scheduler")]
    scheduler_logs = "\n".join(lines) + "\n" if lines else ""

    now = datetime.timestamp(datetime.now())
    if not os.path.exists("docker-compose-logs"):
        os.makedirs("docker-compose-logs", exist_ok=True)
    try:
        with open(f"docker-compose-logs/full-{now}.logs", "w+", encoding="utf-8") as log_file:
            log_file.write(compose_logs)

        with open(f"docker-compose-logs/scheduler-{now}.logs", "w+", encoding="utf-8") as log_file:
            log_file.write(scheduler_logs)
    except (UnicodeDecodeError, IOError) as e:
        print("Failed to write log file for docker tests")

    compose.stop()
