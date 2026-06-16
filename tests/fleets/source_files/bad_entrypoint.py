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

"""Bad entrypoint that always fails — used to test the error path."""

# The [public] prefix is required so the wrapper's log filter writes this
# line to the user log file (PUBLIC_LOG_PATH).
print("[public] Intentional failure for testing", flush=True)
raise RuntimeError("Intentional failure for testing")
