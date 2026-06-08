"""Entrypoint script for fleets integration test jobs."""

import time

from qiskit_serverless import get_arguments, save_result


def main():
    """Load job arguments via SDK, process them, and save the result."""
    args = get_arguments()

    print(f"[public] Hello from fleets! name={args.get('name', 'world')}")
    print(f"Processing internally: {args}")
    time.sleep(2)

    result = {"greeting": f"Hello, {args.get('name', 'world')}!", "status": "completed"}
    save_result(result)

    print("[public] Done")


if __name__ == "__main__":
    main()
