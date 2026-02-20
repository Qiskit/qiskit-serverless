import time

from qiskit_serverless import Job


def wait_for_logs(job: Job, contain: str, timeout: int = 60 * 5):
    """Wait for a job to contain a specific string."""
    start = time.perf_counter()
    deadline = start + timeout

    while True:
        if time.perf_counter() > deadline:
            print(job.logs())
            raise TimeoutError("Timeout waiting for specific string in logs")

        logs = job.logs()
        if contain in logs:
            elapsed = time.perf_counter() - start
            print(f"Detected '{contain}' string in job logs after {elapsed:.2f}s")
            return logs

        time.sleep(0.5)


def wait_for_terminal_state(job: Job, timeout: int = 60 * 5):
    """Wait for a job to reach a terminal state."""
    deadline = time.perf_counter() + timeout

    while True:
        if time.perf_counter() > deadline:
            print(job.logs())
            raise TimeoutError(f"Timeout waiting for job to reach terminal state: {job.status()}")

        if job.in_terminal_state():
            break

        time.sleep(0.5)
