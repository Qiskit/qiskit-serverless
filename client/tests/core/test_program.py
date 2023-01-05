"""Tests jobs."""
import os

from ray.dashboard.modules.job.common import JobStatus
from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless
from quantum_serverless.core.job import Job
from quantum_serverless.core.program import Program
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


def test_program():
    """Integration test for programs."""

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 8265)
        port = compose.get_service_port("testrayhead", 8265)

        serverless = QuantumServerless(
            {
                "providers": [
                    {
                        "name": "docker",
                        "compute_resource": {
                            "name": "docker",
                            "host": host,
                            "port_job_server": port,
                        },
                    }
                ]
            }
        ).set_provider("docker")

        wait_for_job_client(serverless)

        program = Program(
            name="simple_job",
            entrypoint="job.py",
            working_dir=resources_path,
            description="description",
            version="0.0.1",
        )

        job = serverless.run_program(program)

        assert isinstance(job, Job)

        wait_for_job_completion(job)

        assert "42" in job.logs()
        assert job.status().is_terminal()
        assert job.status() == JobStatus.SUCCEEDED

        recovered_job = serverless.get_job_by_id(job.job_id)
        assert recovered_job.job_id == job.job_id
        assert "42" in recovered_job.logs()
        assert recovered_job.status().is_terminal()
        assert recovered_job.status() == JobStatus.SUCCEEDED
        assert isinstance(job.stop(), bool)
