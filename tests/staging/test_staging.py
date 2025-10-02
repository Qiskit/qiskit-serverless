# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os


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

        reference_job_ids = [res[0] for res in result["results"]]
        reference_session_ids = [res[1] for res in result["results"]]
        assert len(reference_job_ids) == 2

        runtime_jobs = serverless_client.runtime_jobs(job.job_id)["runtime_jobs"]
        runtime_job_ids = [job["runtime_job"] for job in runtime_jobs]
        session_ids = [job["runtime_session"] for job in runtime_jobs]

        assert runtime_job_ids == reference_job_ids
        assert session_ids == reference_session_ids

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
            entrypoint="pattern_with_runtime_wrapper_1.py",
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

        # Attempt to stop the job
        stop_response = serverless_client.stop(job_id)

        # Validate the response
        assert isinstance(stop_response, dict)
        assert stop_response.get("status") in ["STOPPED"]
