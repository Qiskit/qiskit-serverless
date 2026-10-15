"""Simple test function for Fleets runner — verifies the full execution pipeline."""

import os
import platform

from qiskit_serverless import get_arguments, save_result


def log(msg):
    """Print with [public] prefix so the wrapper routes it to the public log."""
    print(f"[public] {msg}", flush=True)


if __name__ == "__main__":
    log("Hello from Code Engine Fleets!")
    log(f"Python: {platform.python_version()}")
    log(f"CPU cores: {os.cpu_count()}")

    try:
        args = get_arguments()
        log(f"Arguments received: {args}")
    except Exception as e:
        log(f"get_arguments failed: {e}")
        args = {}

    backend_name = args.get("backend_name", "not provided")
    molecule = args.get("molecule", {})
    log(f"Backend: {backend_name}")
    log(f"Molecule atoms: {molecule.get('atoms', [])}")

    result = {
        "status": "ok",
        "backend_name": backend_name,
        "molecule": molecule,
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }

    save_result(result)
    log("Result saved successfully.")
    log("Done.")
