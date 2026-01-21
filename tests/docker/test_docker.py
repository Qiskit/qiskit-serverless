# pylint: disable=import-error, invalid-name
"""Tests jobs."""
from datetime import datetime, timezone
import os
from time import sleep
from uuid import uuid4

from pytest import raises, mark

from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit

from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
    QiskitServerlessException,
)


resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestFunctionsDocker:
    """Test class for integration testing with docker."""

    @mark.order(1)
    def test_simple_function(self, serverless_client: ServerlessClient):
        """Integration test function uploading."""
        simple_function = QiskitFunction(
            title="my-first-pattern",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )

        runnable_function = serverless_client.upload(simple_function)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        runnable_function = serverless_client.function(simple_function.title)

        assert runnable_function is not None
        assert runnable_function.type == "GENERIC"

        job = runnable_function.run()

        # pylint: disable=duplicate-code
        assert job is not None
        assert job.result() is not None
        allowed_keys = {"00", "11"}
        for entry in job.result().get("results", []):
            assert set(entry.keys()).issubset(allowed_keys)

        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    # failed jobs has logs "", so the result() can't get the error from the logs
    def test_function_with_import_errors(self, serverless_client: ServerlessClient):
        """Integration test for faulty function run."""
        function = QiskitFunction(
            title="pattern-with-errors",
            entrypoint="pattern_with_errors.py",
            working_dir=resources_path,
        )

        runnable_function = serverless_client.upload(function)

        assert runnable_function is not None

        job = runnable_function.run()

        assert job is not None
        expected_message = (
            "ImportError: attempted relative import with no known parent package"
        )

        print("--- Test result")
        with raises(QiskitServerlessException) as exc_info:
            job.result()

        print(f"exc_info.value: {exc_info}")
        print(f"exc_info.value: {exc_info.value}")
        print(f"exc_info.value expected : {expected_message}")
        print(f"job.status() : {job.status()}")
        print(f"job.logs() : {job.logs()}")

        assert expected_message in str(exc_info.value)

        assert job.status() == "ERROR"
        assert isinstance(job.logs(), str)

    def test_function_with_arguments(self, serverless_client: ServerlessClient):
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

        runnable_function = serverless_client.upload(arguments_function)

        job = runnable_function.run(circuit=circuit)

        assert job is not None
        assert job.result() is not None
        allowed_keys = {"00", "11"}
        for entry in job.result().get("results", []):
            assert set(entry.keys()).issubset(allowed_keys)
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
        assert job.result() == {"hours": 3}
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
            details_index = str(e).find(f"Dependency `{dependency}` is not allowed")
            return code_index > 0 and details_index > 0

        with raises(QiskitServerlessException, check=exceptionCheck):
            serverless_client.upload(function)

    def test_distributed_workloads(self, serverless_client: ServerlessClient):
        """Integration test for Functions for distributed workloads."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-with-parallel-workflow",
            entrypoint="pattern_with_parallel_workflow.py",
            working_dir=resources_path,
        )
        runnable_function = serverless_client.upload(function)

        job = runnable_function.run(circuits=circuits)

        assert job is not None
        assert job.result() is not None
        allowed_keys = {"00", "11", "01", "10"}
        for entry in job.result().get("results", []):
            assert set(entry.keys()).issubset(allowed_keys)
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_multiple_runs(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        circuits = [random_circuit(2, 2) for _ in range(3)]
        for circuit in circuits:
            circuit.measure_all()

        function = QiskitFunction(
            title="pattern-to-fetch-results",
            entrypoint="pattern.py",
            working_dir=resources_path,
        )
        runnable_function = serverless_client.upload(function)

        job1 = runnable_function.run()
        job2 = runnable_function.run()

        assert job1 is not None
        assert job2 is not None

        assert job1.job_id != job2.job_id

        retrieved_job1 = serverless_client.job(job1.job_id)
        retrieved_job2 = serverless_client.job(job2.job_id)

        assert retrieved_job1.result() is not None
        assert retrieved_job2.result() is not None

        assert isinstance(retrieved_job1.logs(), str)
        assert isinstance(retrieved_job2.logs(), str)

    @mark.skip(
        reason="Images are not working in tests yet and "
        + "LocalClient does not manage image instead of working_dir+entrypoint"
    )
    def test_error(self, serverless_client: ServerlessClient):
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

        runnable_function = serverless_client.upload(function_with_custom_image)

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

    def test_dependencies_versions(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        deps = serverless_client.dependencies_versions()

        assert deps == ["pendulum>=3.0.0", "wheel>=0.45.1"]

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

        while job_1.status() == "QUEUED" or job_1.status() == "INITIALIZING":
            sleep(1)

        while job_2.status() == "QUEUED" or job_2.status() == "INITIALIZING":
            sleep(1)

        assert job_1.status() == "RUNNING"
        assert job_2.status() == "RUNNING"

    # pylint: disable=too-many-locals
    def test_get_filtered_jobs(self, serverless_client: ServerlessClient):
        """Integration test for filtering jobs."""

        function_1 = QiskitFunction(
            title=f"test-exec-1-{uuid4()}",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        function_2 = QiskitFunction(
            title=f"test-exec-2-{uuid4()}",
            entrypoint="pattern_wait.py",
            working_dir=resources_path,
        )
        runnable_function_1 = serverless_client.upload(function_1)
        runnable_function_2 = serverless_client.upload(function_2)

        before_create = datetime.now(timezone.utc)
        sleep(0.1)
        job_1_1 = runnable_function_1.run()
        job_1_2 = runnable_function_1.run()
        sleep(0.1)
        before_last = datetime.now(timezone.utc)
        job_2 = runnable_function_2.run()
        sleep(0.1)
        after_last = datetime.now(timezone.utc)

        non_filtered_jobs = serverless_client.jobs()
        non_filtered_jobs_1 = runnable_function_1.jobs()
        non_filtered_jobs_2 = runnable_function_2.jobs()

        limit_jobs = runnable_function_1.jobs(limit=1)
        offset_jobs = runnable_function_1.jobs(offset=1)
        date_before_jobs = serverless_client.jobs(created_after=before_create)
        date_middle_jobs = serverless_client.jobs(created_after=before_last)
        date_after_jobs = serverless_client.jobs(created_after=after_last)

        while job_1_1.status() == "QUEUED" or job_1_1.status() == "INITIALIZING":
            sleep(0.5)
        running_jobs = serverless_client.jobs(status="RUNNING")

        assert len(non_filtered_jobs) >= 3
        assert len(non_filtered_jobs_1) == 2
        assert len(non_filtered_jobs_2) == 1
        assert non_filtered_jobs_2[0].job_id == job_2.job_id

        assert len(running_jobs) >= 1

        assert len(date_before_jobs) == 3
        assert len(date_middle_jobs) == 1
        assert len(date_after_jobs) == 0

        assert len(limit_jobs) == 1
        assert limit_jobs[0].job_id == job_1_2.job_id

        assert len(offset_jobs) == 1
        assert offset_jobs[0].job_id == job_1_1.job_id

        while job_1_1.status() == "RUNNING":
            sleep(1)
        while job_1_2.status() == "RUNNING":
            sleep(1)
        while job_2.status() == "RUNNING":
            sleep(1)

        succeeded_jobs = serverless_client.jobs(status="SUCCEEDED")
        assert len(succeeded_jobs) >= 3

    def test_logs(self, serverless_client: ServerlessClient):
        """Integration test for logs."""

        function = QiskitFunction(
            title="logs_function",
            entrypoint="logger.py",
            working_dir=resources_path,
        )
        function = serverless_client.upload(function)
        job = function.run()

        while not job.in_terminal_state():
            sleep(1)

        assert job.logs().endswith(
            """INFO:user: User log
INFO:user: User multiline
INFO:user: log
WARNING:user: User log
ERROR:user: User log
INFO:provider: Provider log
INFO:provider: Provider multiline
INFO:provider: log
WARNING:provider: Provider log
ERROR:provider: Provider log
"""
        )

    def test_wrong_function_name(self, serverless_client: ServerlessClient):
        """Integration test for retrieving a function that isn't accessible."""

        arguments_function = QiskitFunction(
            title="pattern-with-arguments",
            entrypoint="pattern_with_arguments.py",
            working_dir=resources_path,
        )

        expected_message = (
            "\n| Message: Http bad request.\n"
            "| Code: 404\n"
            "| Details: User program 'wrong-title' was not found or you do not "
            "have permission to view it."
        )

        serverless_client.upload(arguments_function)

        with raises(QiskitServerlessException) as exc_info:
            serverless_client.function("wrong-title")

        assert str(exc_info.value) == expected_message

    def test_provider_logs(self, serverless_client: ServerlessClient):
        """Integration test for logs."""

        function = QiskitFunction(
            title="logs_function_2", entrypoint="logger.py", working_dir=resources_path
        )
        function = serverless_client.upload(function)
        job = function.run()

        while not job.in_terminal_state():
            sleep(1)

        with raises(QiskitServerlessException) as exc_info:
            job.provider_logs()

        assert (
            str(exc_info.value).strip()
            == f"""
| Message: Http bad request.
| Code: 403
| Details: You don't have access to job [{job.job_id}]
""".strip()
        )
