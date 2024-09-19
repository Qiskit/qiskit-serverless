"""Tests jobs."""
import os

from testcontainers.compose import DockerCompose

from qiskit_serverless import BaseClient
from qiskit_serverless.core import ComputeResource
from qiskit_serverless.core.job import Job
from qiskit_serverless.core.function import QiskitFunction
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


def test_program():
    """Integration test for program."""

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yaml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 8265)
        port = compose.get_service_port("testrayhead", 8265)

        serverless = BaseClient(
            name="docker",
            compute_resource=ComputeResource(
                name="docker", host=host, port_job_server=port
            ),
        )
        wait_for_job_client(serverless)

        program = QiskitFunction(
            title="simple_job",
            entrypoint="job.py",
            working_dir=resources_path,
            description="description",
            version="0.0.1",
        )

        job = serverless.run(program)

        assert isinstance(job, Job)

        wait_for_job_completion(job)

        assert "42" in job.logs()
        assert job.in_terminal_state()
        assert job.status() == "DONE"

        recovered_job = serverless.get_job_by_id(job.job_id)
        assert recovered_job.job_id == job.job_id
        assert "42" in recovered_job.logs()
        assert recovered_job.in_terminal_state()
        assert recovered_job.status() == "DONE"
        assert isinstance(job.cancel(), bool)
