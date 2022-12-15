"""Tests jobs."""
import os

from ray.dashboard.modules.job.common import JobStatus
from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


# pylint: disable=duplicate-code
def test_jobs():
    """Integration test for jobs."""

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 8265)
        port = compose.get_service_port("testrayhead", 8265)

        serverless = QuantumServerless(
            {
                "providers": [
                    {
                        "name": "test_docker",
                        "compute_resource": {
                            "name": "test_docker",
                            "host": host,
                            "port_job_server": port,
                        },
                    }
                ]
            }
        ).set_provider("test_docker")

        wait_for_job_client(serverless)

        job = serverless.run_job(
            entrypoint="python job.py",
            runtime_env={
                "working_dir": resources_path,
            },
        )

        wait_for_job_completion(job)

        assert "42" in job.logs()
        assert job.status().is_terminal()
        assert job.status() == JobStatus.SUCCEEDED

        recovered_job = serverless.get_job_by_id(job.job_id)
        assert recovered_job.job_id == job.job_id
        assert "42" in recovered_job.logs()
        assert recovered_job.status().is_terminal()
        assert recovered_job.status() == JobStatus.SUCCEEDED
