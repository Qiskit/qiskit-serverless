# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os

from pytest import fixture, raises, mark

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import QiskitFunction
from qiskit_serverless.core.client import BaseClient
from qiskit_serverless.exception import QiskitServerlessException


resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestFunctionsDocker:
    """Test class for integration testing with docker."""

    @fixture(scope="class")
    def simple_function(self):
        """Fixture of a simple function"""
        return QiskitFunction(
            title="my-first-pattern",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )

    @mark.order(1)
    def test_simple_function(self, client: BaseClient, simple_function: QiskitFunction):
        """Integration test function uploading."""

        runnable_function = client.upload(simple_function)

        assert runnable_function is not None

        runnable_function = client.function(simple_function.title)

        assert runnable_function is not None

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_function_with_arguments(self, client: BaseClient):
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

        runnable_function = client.upload(arguments_function)

        job = runnable_function.run(circuit=circuit)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_dependencies_function(self, client: BaseClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum"],
        )

        runnable_function = client.upload(function)

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_distributed_workloads(self, client: BaseClient):
        """Integration test for Functions for distributed workloads."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-with-parallel-workflow",
            entrypoint="pattern_with_parallel_workflow.py",
            working_dir=resources_path,
        )
        runnable_function = client.upload(function)

        job = runnable_function.run(circuits=circuits)

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_multiple_runs(self, client: BaseClient):
        """Integration test for run functions multiple times."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-to-fetch-results",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )
        runnable_function = client.upload(function)

        job1 = runnable_function.run()
        job2 = runnable_function.run()

        assert job1 is not None
        assert job2 is not None

        assert job1.job_id != job2.job_id

        retrieved_job1 = client.job(job1.job_id)
        retrieved_job2 = client.job(job2.job_id)

        assert retrieved_job1.result() is not None
        assert retrieved_job2.result() is not None

        assert isinstance(retrieved_job1.logs(), str)
        assert isinstance(retrieved_job2.logs(), str)

    def test_error(self, client: BaseClient):
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

        runnable_function = client.upload(function_with_custom_image)

        job = runnable_function.run(message="Argument for the custum function")

        with raises(QiskitServerlessException):
            job.result()
