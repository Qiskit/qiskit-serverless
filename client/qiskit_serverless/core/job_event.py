# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
Job Event data class
"""

from dataclasses import dataclass


@dataclass
class JobEvent:  # pylint: disable=too-many-instance-attributes
    """Job Event data.

    Args:
        workers: number of worker pod when auto scaling is NOT enabled
        auto_scaling: set True to enable auto scaling of the workers
        min_workers: minimum number of workers when auto scaling is enabled
        max_workers: maximum number of workers when auto scaling is enabled
    """

    event_type: str
    origin: str
    context: str
    created: str
    data: dict
