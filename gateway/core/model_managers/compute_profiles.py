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

"""Compute profile model manager."""

import logging
from typing import Optional, TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import ComputeProfiles

logger = logging.getLogger("core.compute_profiles")


class ComputeProfilesQuerySet(QuerySet):
    """Compute profile query set to transform into a manager."""

    def get_by_id(self, compute_profile_id: Optional[str]) -> Optional["ComputeProfiles"]:
        """Return the profile row for an identifier, or None.

        Args:
            compute_profile_id: Code Engine compute profile identifier
                (e.g., ``gx3d-24x120x1a100p``). May be None.

        Returns:
            ComputeProfiles | None: the matching profile, or None when the
            identifier is empty or no row exists for it.
        """
        if not compute_profile_id:
            return None
        return self.filter(pk=compute_profile_id).first()
