# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.


"""Test state handlers."""
import os

from ray.dashboard.modules.job.common import JobStatus
from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless
from quantum_serverless.core.state import RedisStateHandler
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


# pylint: disable=duplicate-code
def test_state():
    """Integration test for jobs."""

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 8265)
        port = compose.get_service_port("testrayhead", 8265)

        redis_host = compose.get_service_host("redis", 6379)
        redis_port = compose.get_service_port("redis", 6379)

        state_handler = RedisStateHandler(redis_host, redis_port)

        state_handler.set("some_key", {"key": "value"})

        assert state_handler.get("some_key") == {"key": "value"}

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
            entrypoint="python job_with_state.py",
            runtime_env={
                "working_dir": resources_path,
            },
        )

        wait_for_job_completion(job)

        assert "42" in job.logs()
        assert job.status().is_terminal()
        assert job.status() == JobStatus.SUCCEEDED

        assert state_handler.get("in_job") == {"k": 42}
        assert state_handler.get("in_other_job") == {"other_k": 42}
