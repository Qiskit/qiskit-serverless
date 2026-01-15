# pylint: disable=import-error, invalid-name
"""Tests jobs using Qiskit Runtime's staging resources."""
import os
import time

from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_serverless import QiskitFunction, ServerlessClient, Job

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


def wait_for_logs(job: Job, contain: str):
    """Wait for a job to contain JOB IDS."""
    timeout = 30  # Secs
    deadline = time.perf_counter() + timeout

    while True:
        if time.perf_counter() > deadline:
            raise TimeoutError("TIMEOUT waiting for JOB IDS")

        if contain in job.logs():
            break
        time.sleep(1)


class TestFunctionsStaging:
    """Integration tests for runtime wrapper with and without session."""

    def _run_and_validate_function(
        self, serverless_client: ServerlessClient, entrypoint: str, num_jobs: int
    ):
        """Run function with given entrypoint and check that runtime job ids and
        session ids reported by the serverless API match those stored at job submission
        time."""
        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint=entrypoint,
            working_dir=resources_path,
            env_vars={
                "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
                "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
                "QISKIT_IBM_URL": os.environ["QISKIT_IBM_URL"],
            },
        )
        my_function = serverless_client.upload(function)

        job = my_function.run()
        result = job.result()

        assert result and "test_eagle" in result["backends"]

        reference_job_ids = result["results"][0]
        reference_session_ids = result["results"][1]
        assert len(reference_job_ids) == num_jobs

        runtime_job_ids = serverless_client.runtime_jobs(job.job_id)
        session_ids = serverless_client.runtime_sessions(job.job_id)

        assert runtime_job_ids == reference_job_ids
        assert sorted(session_ids) == sorted(reference_session_ids)

        # cancel runtime jobs after running to avoid wasting resources
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ["QISKIT_IBM_TOKEN"],
            instance=os.environ["QISKIT_IBM_INSTANCE"],
            url=os.environ["QISKIT_IBM_URL"],
        )

        job.cancel(service)

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
                "QISKIT_IBM_URL": os.environ["QISKIT_IBM_URL"],
            },
        )

        my_function = serverless_client.upload(function)

        job = my_function.run()
        job_id = job.job_id

        wait_for_logs(job, "JOB IDS")

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id)

        # Validate the response
        assert isinstance(stop_response, str)
        assert "QiskitRuntimeService not found" in stop_response
        assert (
            "Job has been stopped" in stop_response
            or "Job already in terminal state" in stop_response
        )
        if "Job has been stopped" in stop_response:
            assert job.status() == "CANCELED"
        else:
            assert job.status() == "DONE"

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
                "QISKIT_IBM_URL": os.environ["QISKIT_IBM_URL"],
            },
        )

        my_function = serverless_client.upload(function)

        job = my_function.run()
        job_id = job.job_id

        wait_for_logs(job, "JOB IDS")

        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ["QISKIT_IBM_TOKEN"],
            instance=os.environ["QISKIT_IBM_INSTANCE"],
            url=os.environ["QISKIT_IBM_URL"],
        )

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id, service)

        # Validate the response
        assert isinstance(stop_response, str)
        assert (
            "Job has been stopped" in stop_response
            or "Job already in terminal state" in stop_response
        )
        assert "Canceled runtime session" in stop_response
        if "Job has been stopped" in stop_response:
            assert job.status() == "CANCELED"
        else:
            assert job.status() == "DONE"

    def test_jobs_no_session(self, serverless_client: ServerlessClient):
        """Test job submission with get_runtime_service without sessions."""
        self._run_and_validate_function(
            serverless_client, "pattern_with_runtime_wrapper_1.py", num_jobs=2
        )

    def test_jobs_with_session(self, serverless_client: ServerlessClient):
        """Test job submission with get_runtime_service with sessions."""
        self._run_and_validate_function(
            serverless_client, "pattern_with_runtime_wrapper_2.py", num_jobs=4
        )
