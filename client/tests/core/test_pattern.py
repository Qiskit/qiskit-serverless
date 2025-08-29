"""Tests jobs."""
import os

from testcontainers.compose import DockerCompose

from qiskit_serverless import RayClient, QiskitFunction
from qiskit_serverless.core.job import Job
from tests.utils import wait_for_ray_ready, wait_for_job_completion

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
        connection_url = f"http://{host}:{port}"

        wait_for_ray_ready(connection_url)

        serverless = RayClient(host=connection_url)

        program = QiskitFunction(
            title="simple_job",
            entrypoint="job.py",
            working_dir=resources_path,
            description="description",
            version="0.0.1",
        )
        uploaded_program = serverless.upload(program)

        job = serverless.run(uploaded_program)

        assert isinstance(job, Job)

        wait_for_job_completion(job)

        assert "42" in job.logs()
        assert job.in_terminal_state()
        assert job.status() == "DONE"

        recovered_job = serverless.job(job.job_id)
        assert recovered_job.job_id == job.job_id
        assert "42" in recovered_job.logs()
        assert recovered_job.in_terminal_state()
        assert recovered_job.status() == "DONE"
        assert isinstance(job.cancel(), bool)
