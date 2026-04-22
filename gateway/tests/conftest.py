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

"""Root pytest configuration — registers custom markers."""


def pytest_configure(config):
    """Register project-wide custom markers.

    Args:
        config: The pytest configuration object.
    """
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require live IBM Cloud credentials " "(skipped unless RUN_INTEGRATION_TESTS=1)",
    )
