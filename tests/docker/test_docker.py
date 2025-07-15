# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os
from time import sleep

from pytest import raises, mark

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import (
    QiskitFunction,
    BaseClient,
    ServerlessClient,
    QiskitServerlessException,
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

    def test_function_with_errors(self, base_client: BaseClient):
        """Integration test for faulty function run."""

        circuit = QuantumCircuit(2)
        circuit.h(0)
        circuit.cx(0, 1)
        circuit.measure_all()
        circuit.draw()

        function = QiskitFunction(
            title="pattern-with-errors",
            entrypoint="pattern_with_errors.py",
            working_dir=resources_path,
        )

        runnable_function = base_client.upload(function)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        runnable_function = base_client.function(function.title)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        job = runnable_function.run(circuit=circuit)

        assert job is not None
        assert job.status() == "ERROR"
        assert isinstance(job.logs(), str)
        expected_message = (
            "ImportError: attempted relative import with no known parent package"
        )
        with self.assertRaises(QiskitServerlessException) as context:
            job.run()

        self.assertEqual(str(context.exception), expected_message)

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

    # local client doesn't make sense here
    # since all dependencies are in the user computer
    def test_function_dependencies_basic(self, serverless_client: ServerlessClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-1",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum"],
        )

        runnable_function = serverless_client.upload(function)

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    # local client doesn't make sense here
    # since all dependencies are in the user computer
    def test_function_dependencies_with_version(
        self, serverless_client: ServerlessClient
    ):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-2",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum==3.0.0"],
        )

        runnable_function = serverless_client.upload(function)

        assert runnable_function is not None

    # local client doesn't make sense here
    # since all dependencies are in the user computer
    def test_function_blocked_dependency(self, serverless_client: ServerlessClient):
        """Integration test for Functions with blocked dependencies."""
        dependency = "notallowedone"
        function = QiskitFunction(
            title="pattern-with-dependencies-3",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=[dependency],
        )

        def exceptionCheck(e: QiskitServerlessException):
            code_index = str(e).find("Code: 400")
            details_index = str(e).find(
                f"non_field_errors: Dependency `{dependency}` is not allowed"
            )
            return code_index > 0 and details_index > 0

        with raises(QiskitServerlessException, check=exceptionCheck):
            serverless_client.upload(function)

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

    @mark.skip(
        reason="Images are not working in tests jet and "
        + "LocalClient does not manage image instead of working_dir+entrypoint"
    )
    def test_error(self, base_client: BaseClient):
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

        runnable_function = base_client.upload(function_with_custom_image)

        job = runnable_function.run(message="Argument for the custum function")

        with raises(QiskitServerlessException):
            job.result()

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

    def test_execute_functions_in_parallel(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        function_1 = QiskitFunction(
            title="parallel-exec-1",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        function_2 = QiskitFunction(
            title="parallel-exec-2",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        runnable_function_1 = serverless_client.upload(function_1)
        runnable_function_2 = serverless_client.upload(function_2)

        job_1 = runnable_function_1.run()
        job_2 = runnable_function_2.run()

        while job_1.status() == "QUEUED" or job_2.status() == "INITIALIZING":
            sleep(1)

        while job_2.status() == "QUEUED" or job_2.status() == "INITIALIZING":
            sleep(1)

        assert job_1.status() == "RUNNING"
        assert job_2.status() == "RUNNING"
