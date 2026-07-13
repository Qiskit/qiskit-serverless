# pylint: disable=import-error, invalid-name
"""Tests jobs."""

from datetime import datetime, timezone
import os
import tempfile
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
from utils import wait_for_logs, wait_for_terminal_state

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")


class TestJobs:
    """Test class for integration testing with docker."""

    def _upload_with_template(self, serverless_client: ServerlessClient, file: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", delete=True, dir=resources_path, suffix=".py"
        ) as tmp:

            with open(
                "../gateway/templates/main.tmpl",
                "r",
                encoding="utf-8",
            ) as template:
                template_content = template.read()
                template_content = template_content.replace("{{mount_path}}", "/runner")
                template_content = template_content.replace("{{package_name}}", file)
                tmp.write(template_content)
                tmp.flush()

            uploaded_function = QiskitFunction(
                title="exception_producer",
                entrypoint=os.path.basename(tmp.name),
                working_dir=resources_path,
            )

            return serverless_client.upload(uploaded_function)

    @mark.skipif(
        os.environ.get("LARGE_LOGS_TEST") != "1",
        reason="Load test for large log volumes -- enable with LARGE_LOGS_TEST=1",
    )
    def test_large_logs(self, serverless_client: ServerlessClient):
        """Stress test: verify gateway handles large log volumes without OOM.

        The rolling deque in _stream_logs_from_ray() bounds memory usage; this test
        confirms the job completes and the most-recent logs are still retrievable.

        Control the log volume with LOGS_SIZE_MB (default 500).
        """
        logs_size_mb = int(os.environ.get("LOGS_SIZE_MB", "500"))

        function = QiskitFunction(
            title="large-logs-function",
            entrypoint="large_logs_generator.py",
            working_dir=resources_path,
            env_vars={"LOGS_SIZE_MB": str(logs_size_mb)},
        )
        function = serverless_client.upload(function)
        job = function.run()

        wait_for_terminal_state(job, timeout=60 * 30)

        assert job.status() == "DONE"
        logs = job.logs()
        assert isinstance(logs, str)
        assert "LARGE_LOGS_DONE" in logs
        print(f"Retrieved {len(logs)} chars of logs for a {logs_size_mb} MB job")

    @mark.skip(reason="Works in docker compose but tails in k8s/staging/production")
    def test_get_filtered_jobs(self, serverless_client: ServerlessClient):  # pylint: disable=too-many-locals
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
