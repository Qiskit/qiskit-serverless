import time

from qiskit_serverless import Job


def wait_for_logs(job: Job, contain: str, timeout: int = 60 * 5):
    """Wait for a job to contain a specific string."""
    start = time.monotonic()
    deadline = start + timeout

    while True:
        elapsed = time.monotonic() - start
        if time.monotonic() > deadline:
            print("Logs:\n" + job.logs())
            raise TimeoutError(f"Timeout waiting for string '{contain}' in logs after {elapsed:.2f}s")

        logs = job.logs()
        if contain in logs:
            print(f"Detected '{contain}' string in job logs after {elapsed:.2f}s")
            return logs

        if job.in_terminal_state():
            raise RuntimeError(f"Job finished without expected string '{contain}' in logs after {elapsed:.2f}s")

        time.sleep(0.5)


def wait_for_terminal_state(job: Job, timeout: int = 60 * 5):
    """Wait for a job to reach a terminal state."""
    start = time.monotonic()
    deadline = start + timeout

    while True:
        elapsed = time.monotonic() - start
        if time.monotonic() > deadline:
            print("Logs:\n" + job.logs())
            raise TimeoutError(f"Timeout waiting for terminated state after {elapsed:.2f}s")

        if job.in_terminal_state():
            break

        time.sleep(0.5)
