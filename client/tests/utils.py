"""Test utils."""
import time

from qiskit_serverless import RayClient
from qiskit_serverless.core.job import Job
from ray.dashboard.modules.job.sdk import JobSubmissionClient


def wait_for_ray_ready(connection_url: str, timeout: int = 60):
    client = None
    must_finish = time.time() + timeout
    while time.time() < must_finish and not client:
        try:
            client = JobSubmissionClient(connection_url)
        except:
            time.sleep(1)


def wait_for_job_completion(job: Job, timeout: int = 60):
    """Utility function that waits for job completion."""
    must_finish = time.time() + timeout
    while time.time() < must_finish:
        if job.in_terminal_state():
            break
        time.sleep(1)
