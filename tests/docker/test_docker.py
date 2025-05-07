# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os
from time import sleep

from pytest import mark

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import (
    QiskitFunction,
    BaseClient,
    ServerlessClient,
)


resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestFunctionsDocker:
    """Test class for integration testing with docker."""

    @mark.order(1)
    def test_simple_function(self, base_client: BaseClient):
        """Integration test function uploading."""
        simple_function = QiskitFunction(
            title="my-first-pattern",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )

        runnable_function = base_client.upload(simple_function)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        runnable_function = base_client.function(simple_function.title)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_function_with_arguments(self, base_client: BaseClient):
        """Integration test for Functions with arguments."""
        circuit = QuantumCircuit(2)
        circuit.h(0)
        circuit.cx(0, 1)
        circuit.measure_all()
        circuit.draw()

        arguments_function = QiskitFunction(
            title="pattern-with-arguments",
            entrypoint="pattern_with_arguments.py",
            working_dir=resources_path,
        )

        runnable_function = base_client.upload(arguments_function)

        job = runnable_function.run(circuit=circuit)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_dependencies_function(self, base_client: BaseClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum"],
        )

        runnable_function = base_client.upload(function)

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_distributed_workloads(self, base_client: BaseClient):
        """Integration test for Functions for distributed workloads."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-with-parallel-workflow",
            entrypoint="pattern_with_parallel_workflow.py",
            working_dir=resources_path,
        )
        runnable_function = base_client.upload(function)

        job = runnable_function.run(circuits=circuits)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_multiple_runs(self, base_client: BaseClient):
        """Integration test for run functions multiple times."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-to-fetch-results",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )
        runnable_function = base_client.upload(function)

        job1 = runnable_function.run()
        job2 = runnable_function.run()

        assert job1 is not None
        assert job2 is not None

        assert job1.job_id != job2.job_id

        retrieved_job1 = base_client.job(job1.job_id)
        retrieved_job2 = base_client.job(job2.job_id)

        assert retrieved_job1.result() is not None
        assert retrieved_job2.result() is not None

        assert isinstance(retrieved_job1.logs(), str)
        assert isinstance(retrieved_job2.logs(), str)

    def test_custom_image(self, serverless_custom_image_yaml_client: BaseClient):
        """Integration test to force an error."""

        description = """
        title: custom-image-function
        description: sample function implemented in a custom image
        arguments:
            service: service created with the account information
            circuit: circuit
            observable: observable
        """

        function_with_custom_image = QiskitFunction(
            title="custom-image-function",
            image="test_function:latest",
            provider=os.environ.get("PROVIDER_ID", "mockprovider"),
            description=description,
        )

        print("Uploading function...")
        runnable_function = serverless_custom_image_yaml_client.upload(
            function_with_custom_image
        )

        print("Running...")
        job = runnable_function.run(message="Argument for the custum function")

        print("Job:")
        print(job)

        print("Result:")
        print(job.result())

    def test_update_sub_status(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        function = QiskitFunction(
            title="pattern-with-sub-status",
            entrypoint="pattern_with_sub_status_and_wait.py",
            working_dir=resources_path,
        )
        runnable_function = serverless_client.upload(function)

        job = runnable_function.run()

        while job.status() == "QUEUED" or job.status() == "INITIALIZING":
            sleep(1)

        assert job.status() == "RUNNING: MAPPING"
