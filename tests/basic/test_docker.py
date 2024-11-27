# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os

from pytest import fixture, raises
from testcontainers.compose import DockerCompose

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import ServerlessClient, QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "./source_files"
)


class TestFunctionsDocker:
    """Test class for integration testing with docker."""

    @fixture(scope="class")
    def serverless_client(self):
        """Fixture for testing Functions."""
        compose = DockerCompose(
            resources_path,
            compose_file_name="../../../docker-compose-dev.yaml",
            pull=True,
        )
        compose.start()

        connection_url = "http://localhost:8000"
        compose.wait_for(f"{connection_url}/backoffice")

        serverless = ServerlessClient(
            token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
            host=os.environ.get("GATEWAY_HOST", connection_url),
        )
        yield serverless

        compose.stop()

    def test_running_program(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""

        function = QiskitFunction(
            title="my-first-pattern",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        my_pattern_function = serverless_client.function("my-first-pattern")

        job = my_pattern_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_arguments_and_resluts(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""
        circuit = QuantumCircuit(2)
        circuit.h(0)
        circuit.cx(0, 1)
        circuit.measure_all()
        circuit.draw()

        function = QiskitFunction(
            title="pattern-with-arguments",
            entrypoint="pattern_with_arguments.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        my_pattern_function = serverless_client.function("pattern-with-arguments")

        job = my_pattern_function.run(circuit=circuit)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_dependencies(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""
        function = QiskitFunction(
            title="pattern-with-dependencies",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum"],
        )
        serverless_client.upload(function)
        my_pattern_function = serverless_client.function("pattern-with-dependencies")

        job = my_pattern_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_distributed_workloads(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-with-parallel-workflow",
            entrypoint="pattern_with_parallel_workflow.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)
        my_pattern_function = serverless_client.function(
            "pattern-with-parallel-workflow"
        )

        job = my_pattern_function.run(circuits=circuits)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_retrieving_past_results(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-to-fetch-results",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)
        my_pattern_function = serverless_client.function("pattern-to-fetch-results")

        job1 = my_pattern_function.run()
        job2 = my_pattern_function.run()

        assert job1 is not None
        assert job2 is not None

        job_id1 = job1.job_id
        job_id2 = job2.job_id

        retrieved_job1 = serverless_client.job(job_id1)
        retrieved_job2 = serverless_client.job(job_id2)

        assert retrieved_job1.result() is not None
        assert retrieved_job2.result() is not None

        assert isinstance(retrieved_job1.logs(), str)
        assert isinstance(retrieved_job2.logs(), str)

    def test_function(self, serverless_client: ServerlessClient):
        """Integration test for Functions."""

        description = """
        title: custom-image-function
        description: sample function implemented in a custom image
        arguments:
            service: service created with the accunt information
            circuit: circuit
            observable: observable
        """

        function_with_custom_image = QiskitFunction(
            title="custom-image-function",
            image="test_function:latest",
            provider=os.environ.get("PROVIDER_ID", "mockprovider"),
            description=description,
        )

        serverless_client.upload(function_with_custom_image)

        my_functions = serverless_client.functions()

        # ???
        for function in my_functions:
            print("Name: " + function.title)
            print(function.description)
            print()

        my_function = serverless_client.function("custom-image-function")
        job = my_function.run(message="Argument for the custum function")

        assert job is not None

        with raises(QiskitServerlessException):
            job.result()
        assert isinstance(job.logs(), str)

        jobs = my_function.jobs()
        print(jobs)
        assert jobs.count != 0
