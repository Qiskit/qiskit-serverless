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

"""Code Engine project QuerySet."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from django.conf import settings
from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import CodeEngineProject

logger = logging.getLogger("core.model_managers.code_engine_projects")


class CodeEngineProjectQuerySet(QuerySet):
    """QuerySet for CodeEngineProject with project selection helpers."""

    def select_for_profile(self, compute_profile: str | None) -> "CodeEngineProject | None":
        """Select an active Code Engine project for the given compute profile.

        Zone resolution: looks up the compute profile in ``FLEETS_PROFILE_ZONE_MAP``.
        Profiles absent from the map (or mapped to ``"any"``) fall back to the
        multi-zone project (zone is null/blank).

        Args:
            compute_profile: Compute profile string, e.g. ``"gx2-8x64x1l40s"``.

        Returns:
            Active :class:`~core.models.CodeEngineProject`, or ``None`` if not found.
        """
        profile_zone_map: dict = settings.FLEETS_PROFILE_ZONE_MAP
        zone = profile_zone_map.get(compute_profile or "")
        qs = self.filter(active=True)

        if zone and zone != "any":
            project = qs.filter(zone=zone).first()
            if not project:
                logger.warning(
                    "No active Code Engine project for zone '%s' (compute profile: %s)", zone, compute_profile
                )
        else:
            project = qs.filter(zone__isnull=True).first() or qs.filter(zone="").first() or qs.first()
            if not project:
                logger.warning("No active Code Engine project available (compute profile: %s)", compute_profile)

        if project:
            logger.info("Selected project [%s] for compute profile [%s]", project.project_name, compute_profile)
        return project
