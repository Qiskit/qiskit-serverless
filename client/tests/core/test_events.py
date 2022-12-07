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


"""Test handlers."""
import json
import os

from testcontainers.compose import DockerCompose

from quantum_serverless import QuantumServerless, run_qiskit_remote, get
from quantum_serverless.core.constrants import (
    META_TOPIC,
    QS_EVENTS_REDIS_HOST,
    QS_EVENTS_REDIS_PORT,
)
from quantum_serverless.core.events import RedisEventHandler
from tests.utils import wait_for_job_client, wait_for_job_completion

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../resources"
)


# pylint: disable=duplicate-code,too-many-locals
def test_events():
    """Integration test for jobs."""

    topic = "test-topic"

    with DockerCompose(
        resources_path, compose_file_name="test-compose.yml", pull=True
    ) as compose:
        host = compose.get_service_host("testrayhead", 10001)
        interactive_port = compose.get_service_port("testrayhead", 10001)
        job_server_port = compose.get_service_port("testrayhead", 8265)

        redis_host = compose.get_service_host("redis", 6379)
        redis_port = compose.get_service_port("redis", 6379)

        events_handler = RedisEventHandler(redis_host, redis_port)

        events_handler.publish(topic, {"some_key": "some_value"})

        for message in events_handler.listen():
            if message.get("type") == "message":
                assert json.loads(message.get("data")) == {"some_key": "some_value"}
            events_handler.unsubscribe()

        serverless = QuantumServerless(
            {
                "providers": [
                    {
                        "name": "test_docker",
                        "compute_resource": {
                            "name": "test_docker",
                            "host": host,
                            "port_job_server": job_server_port,
                            "port_interactive": interactive_port,
                        },
                    }
                ]
            }
        ).set_provider("test_docker")

        @run_qiskit_remote(target={"cpu": 1, "qpu": 2}, events=events_handler)
        def ultimate():
            return 42

        events_handler.subscribe(META_TOPIC)

        with serverless:
            result = get(ultimate())
            assert result == 42

        for message in events_handler.listen():
            if message.get("type") == "message":
                message_data = json.loads(message.get("data"))
                assert message_data.get("layer") == "qs"
                assert message_data.get("function_meta", {}).get("name") == "ultimate"
                assert message_data.get("resources") == {
                    "cpu": 1,
                    "gpu": 0,
                    "qpu": 2,
                    "mem": 1,
                    "resources": None,
                    "env_vars": None,
                    "pip": None,
                }

            events_handler.unsubscribe()

        wait_for_job_client(serverless)

        events_handler.subscribe(META_TOPIC)

        job = serverless.run_job(
            entrypoint="python job.py",
            runtime_env={
                "working_dir": resources_path,
                "env_vars": {
                    QS_EVENTS_REDIS_HOST: "redis",
                    QS_EVENTS_REDIS_PORT: "6379",
                },
            },
        )

        wait_for_job_completion(job)

        messages = []
        for message in events_handler.listen():
            if message.get("type") == "message":
                message_data = json.loads(message.get("data"))
                messages.append(message_data)
                assert message_data.get("layer") == "qs"
                assert message_data.get("function_meta", {}).get("name") == "ultimate"
            events_handler.unsubscribe()
        assert len(messages) == 10
