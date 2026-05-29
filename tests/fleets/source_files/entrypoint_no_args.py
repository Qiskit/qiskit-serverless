"""Entrypoint for testing jobs submitted without arguments."""

from qiskit_serverless import get_arguments, save_result


def main():
    """Load arguments (expecting empty dict) and save result."""
    args = get_arguments()
    print("[public] No-args job running")
    save_result({"received_args": args, "status": "completed"})


if __name__ == "__main__":
    main()
