# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Entrypoint script for fleets integration test jobs."""

import time

from qiskit_serverless import get_arguments, save_result


def main():
    """Load job arguments via SDK, process them, and save the result."""
    args = get_arguments()

    print(f"[public] Hello from fleets! name={args.get('name', 'world')}", flush=True)
    print(f"Processing internally: {args}", flush=True)

    # Configurable so the cancel test can keep the job RUNNING well beyond the
    # cancel-propagation latency; defaults to a short delay for the happy path.
    time.sleep(int(args.get("sleep_seconds", 2)))

    result = {"greeting": f"Hello, {args.get('name', 'world')}!", "status": "completed"}
    save_result(result)

    print("[public] Done", flush=True)


if __name__ == "__main__":
    main()
