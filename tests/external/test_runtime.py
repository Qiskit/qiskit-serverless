# pylint: disable=import-error, invalid-name
"""Tests jobs using Qiskit Runtime's staging resources."""

import os

from qiskit_serverless import QiskitFunction, ServerlessClient
from utils import wait_for_logs

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")


def runtime_env_vars(backend1: str, backend2: str):
    """Build runtime environment variables for function execution."""
    return {
        "QISKIT_IBM_CHANNEL": os.environ.get("QISKIT_IBM_CHANNEL", "ibm_quantum_platform"),
        "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
        "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
        "QISKIT_IBM_URL": os.environ["QISKIT_IBM_URL"],
        "QISKIT_IBM_BACKEND_1": backend1,
        "QISKIT_IBM_BACKEND_2": backend2,
    }


class TestRuntimeIntegration:
    """Integration tests for runtime wrapper with and without session."""

    def _run_and_validate_function(  # pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
        self,
        serverless_client: ServerlessClient,
        working_backends: list,
        runtime_service,
        entrypoint: str,
        num_jobs: int,
    ):
        """Run function with given entrypoint and check that runtime job ids and
        session ids reported by the serverless API match those stored at job submission
        time."""
        env_vars = runtime_env_vars(working_backends[0], working_backends[1])

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint=entrypoint,
            working_dir=resources_path,
            env_vars=env_vars,
        )
        my_function = serverless_client.upload(function)

        job = my_function.run()
        try:
            result = job.result()
        except Exception as error:
            print("Job failed. Logs:")
            print(job.logs())
            raise error

        assert result and working_backends[0] in result["backends"]

        reference_job_ids = result["results"][0]
        reference_session_ids = result["results"][1]
        assert len(reference_job_ids) == num_jobs

        runtime_job_ids = serverless_client.runtime_jobs(job.job_id)
        session_ids = serverless_client.runtime_sessions(job.job_id)

        assert runtime_job_ids == reference_job_ids
        assert sorted(session_ids) == sorted(reference_session_ids)

        # cancel runtime jobs after running to avoid wasting resources
        job.cancel(runtime_service)

    def test_stop_job(self, serverless_client: ServerlessClient, working_backends):
        """Integration test for stopping a job."""

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint="runtime_stop.py",
            working_dir=resources_path,
            env_vars=runtime_env_vars(working_backends[0], working_backends[1]),
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
        assert "Job has been stopped" in stop_response or "Job already in terminal state" in stop_response
        if "Job has been stopped" in stop_response:
            assert job.status() == "CANCELED"
        else:
            assert job.status() == "DONE"

    def test_stop_job_service(
        self,
        serverless_client: ServerlessClient,
        working_backends,
        qiskit_runtime_service,
    ):
        """Integration test for stopping a job given a runtime service."""

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint="runtime_stop.py",
            working_dir=resources_path,
            env_vars=runtime_env_vars(working_backends[0], working_backends[1]),
        )

        my_function = serverless_client.upload(function)

        job = my_function.run()
        job_id = job.job_id

        wait_for_logs(job, "JOB IDS")

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id, qiskit_runtime_service)

        # Validate the response
        assert isinstance(stop_response, str)
        assert "Job has been stopped" in stop_response or "Job already in terminal state" in stop_response
        assert "Canceled runtime session" in stop_response
        if "Job has been stopped" in stop_response:
            assert job.status() == "CANCELED"
        else:
            assert job.status() == "DONE"

    def test_jobs_no_session(
        self,
        serverless_client: ServerlessClient,
        working_backends,
        qiskit_runtime_service,
    ):
        """Test job submission with get_runtime_service without sessions."""
        self._run_and_validate_function(
            serverless_client,
            working_backends,
            qiskit_runtime_service,
            "runtime_job.py",
            num_jobs=2,
        )

    def test_jobs_with_session(
        self,
        serverless_client: ServerlessClient,
        working_backends,
        qiskit_runtime_service,
    ):
        """Test job submission with get_runtime_service with sessions."""
        self._run_and_validate_function(
            serverless_client,
            working_backends,
            qiskit_runtime_service,
            "runtime_session.py",
            num_jobs=4,
        )
