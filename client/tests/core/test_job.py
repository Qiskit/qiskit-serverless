"""Tests jobs."""
import os

from ray.dashboard.modules.job.common import JobStatus
from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


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
        )

        serverless.set_provider("test_docker")

        job = serverless.run_job(
            entrypoint="python job.py",
            runtime_env={
                "working_dir": resources_path,
            },
        )

        assert job.status() in [JobStatus.RUNNING, JobStatus.PENDING]
