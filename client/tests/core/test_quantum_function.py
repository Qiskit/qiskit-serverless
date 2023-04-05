"""Tests jobs."""
import os
from unittest import TestCase

import numpy as np
from ray.dashboard.modules.job.common import JobStatus
from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless, Provider
from quantum_serverless.core import ComputeResource
from quantum_serverless.core.job import Job
from quantum_serverless.core.quantum_function import QuantumFunction
from quantum_serverless.exception import QuantumServerlessException
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


class TestQuantumFunction(TestCase):
    """TestQuantumFunction."""

    def test_arguments_validation(self):
        """Tests arguments validation."""
        quantum_function = QuantumFunction(
            title="awesome_quantum_function",
            entrypoint="awesome.py",
            arguments={"one": 1, "json": {"one": 1, "two": 2}},
        )
        self.assertIsInstance(quantum_function, QuantumFunction)

        with self.assertRaises(QuantumServerlessException):
            QuantumFunction(
                title="awesome_quantum_function",
                entrypoint="awesome.py",
                arguments={"one": 1, "json": {"one": np.array([1]), "two": 2}},
            )


def test_quantum_function():
    """Integration test for quantum function."""

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 8265)
        port = compose.get_service_port("testrayhead", 8265)

        provider = Provider(
            name="docker",
            compute_resource=ComputeResource(
                name="docker", host=host, port_job_server=port
            ),
        )
        serverless = QuantumServerless(provider).set_provider("docker")

        wait_for_job_client(serverless)

        quantum_function = QuantumFunction(
            title="simple_job",
            entrypoint="job.py",
            working_dir=resources_path,
            description="description",
            version="0.0.1",
        )

        job = serverless.run(quantum_function)

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
