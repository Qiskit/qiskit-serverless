"""Test utils."""
import time

from quantum_serverless import QuantumServerless
from quantum_serverless.core.job import Job


def wait_for_job_client(serverless: QuantumServerless, timeout: int = 60):
    """Utility function that wait for job client to awake."""
    must_finish = time.time() + timeout
    while time.time() < must_finish:
        if serverless.job_client is not None:
            break
        time.sleep(1)


def wait_for_job_completion(job: Job, timeout: int = 60):
    """Utility function that waits for job completion."""
    must_finish = time.time() + timeout
    while time.time() < must_finish:
        if job.status().is_terminal():
            break
        time.sleep(1)
