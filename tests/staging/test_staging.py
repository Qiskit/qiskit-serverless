# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os

from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
)

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestFunctionsStaging:
    """Integration tests for runtime wrapper with and without session."""

    def _run_and_validate_function(
        self, serverless_client: ServerlessClient, entrypoint: str
    ):
        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint=entrypoint,
            working_dir=resources_path,
            env_vars={
                "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
                "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
            },
        )
        serverless_client.upload(function)
        my_function = serverless_client.function("test-runtime-wrapper")

        job = my_function.run()
        result = job.result()

        assert result and "test_eagle" in result["backends"]

        reference_job_ids = result["results"][0]
        reference_session_ids = result["results"][1]
        assert len(reference_job_ids) == 2

        runtime_job_ids = serverless_client.runtime_jobs(job.job_id)
        session_ids = serverless_client.runtime_sessions(job.job_id)

        assert runtime_job_ids == reference_job_ids
        assert session_ids == reference_session_ids

        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ["QISKIT_IBM_TOKEN"],
            instance=os.environ["QISKIT_IBM_INSTANCE"],
            url="https://test.cloud.ibm.com",
        )

        job.stop(service)

    def test_jobs_no_session(self, serverless_client: ServerlessClient):
        self._run_and_validate_function(
            serverless_client, "pattern_with_runtime_wrapper_1.py"
        )

    def test_jobs_with_session(self, serverless_client: ServerlessClient):
        self._run_and_validate_function(
            serverless_client, "pattern_with_runtime_wrapper_2.py"
        )

    def test_stop_job(self, serverless_client: ServerlessClient):
        """Integration test for stopping a job."""

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint="pattern_with_stop.py",
            working_dir=resources_path,
            env_vars={
                "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
                "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
            },
        )

        serverless_client.upload(function)
        my_function = serverless_client.function("test-runtime-wrapper")

        job = my_function.run()
        job_id = job.job_id

        while True:
            if "JOB IDS" in job.logs():
                break

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id)

        # Validate the response
        assert isinstance(stop_response, str)
        assert "Job has been stopped" in stop_response
        assert "QiskitRuntimeService not found" in stop_response
        assert job.status() == "CANCELED"

    def test_stop_job_service(self, serverless_client: ServerlessClient):
        """Integration test for stopping a job given a runtime service."""

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint="pattern_with_stop.py",
            working_dir=resources_path,
            env_vars={
                "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
                "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
            },
        )

        serverless_client.upload(function)
        my_function = serverless_client.function("test-runtime-wrapper")

        job = my_function.run()
        job_id = job.job_id

        while True:
            if "JOB IDS" in job.logs():
                break

        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ["QISKIT_IBM_TOKEN"],
            instance=os.environ["QISKIT_IBM_INSTANCE"],
            url="https://test.cloud.ibm.com",
        )

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id, service)

        # Validate the response
        assert isinstance(stop_response, str)
        assert "Job has been stopped" in stop_response
        assert "Cancelled runtime session" in stop_response
        assert job.status() == "CANCELED"
