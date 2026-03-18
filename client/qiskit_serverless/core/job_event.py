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

from dataclasses import dataclass, fields


@dataclass
class JobEvent:  # pylint: disable=too-many-instance-attributes
    """
    Job Event data.

    Args:
        event_type: Type of the event ("ERROR", "STATUS_CHANGE"...)
        origin: Where the event is raised ("API", "SCHEDULER"...)
        context: Where the event is raised ("SEND_ERROR", "SET_SUB_STATUS"...)
        created: The date of creation
        data: Additional data for the event type, usually a dict
    """

    event_type: str
    origin: str
    context: str
    created: str
    data: dict

    @classmethod
    def from_json(cls, data: dict):
        """Reconstructs JobEvent from dictionary."""
        field_names = set(f.name for f in fields(JobEvent))
        return JobEvent(**{k: v for k, v in data.items() if k in field_names})
