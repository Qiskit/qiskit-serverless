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

"""Mock Runner module for provider function integration tests.

In production, this file lives at /runner/runner.py in the provider's Docker
image. The rendered main.tmpl does:
    sys.path.append("/runner")
    from runner import Runner
    Runner().run(arguments)
"""

from qiskit_serverless import get_logger, get_provider_logger, save_result


class Runner:  # pylint: disable=too-few-public-methods
    """Mock provider Runner for integration tests."""

    def run(self, arguments: dict) -> dict:
        """Execute the provider function logic.

        Args:
            arguments: Dict of job arguments from get_arguments().

        Returns:
            Result dict.
        """
        name = arguments.get("name", "world")

        # Provider job: public logger ([PUBLIC]) is visible to the job author;
        # provider logger ([PRIVATE]) stays in the provider-only log.
        public = get_logger()
        provider = get_provider_logger()
        public.info("Hello from fleets!")
        public.info("Name: %s", name)
        provider.info("Processing internally")
        public.info("Done")

        result = {"greeting": f"Hello, {name}!", "status": "completed"}
        save_result(result)
        return result
