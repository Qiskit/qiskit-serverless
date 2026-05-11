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

"""Code Engine project selection helpers."""

from __future__ import annotations

import logging

from django.conf import settings

from core.models import CodeEngineProject

logger = logging.getLogger("core.model_managers.code_engine_projects")


def select_ce_project(compute_profile: str | None):
    """Select an active Code Engine project for the given compute profile.

    Zone resolution: looks up the compute profile in ``FLEETS_PROFILE_ZONE_MAP``.
    Profiles absent from the map (or mapped to ``"any"``) fall back to the
    multi-zone project (zone is null/blank).

    Args:
        compute_profile: Compute profile string, e.g. ``"gx2-8x64x1l40s"``.

    Returns:
        Active :class:`~core.models.CodeEngineProject`.

    Raises:
        ValueError: If no active project is available for the requested zone.
    """
    profile_zone_map: dict = settings.FLEETS_PROFILE_ZONE_MAP
    zone = profile_zone_map.get(compute_profile or "")
    qs = CodeEngineProject.objects.filter(active=True)

    if zone and zone != "any":
        project = qs.filter(zone=zone).first()
        if not project:
            raise ValueError(f"No active Code Engine project for zone '{zone}'")
    else:
        project = qs.filter(zone__isnull=True).first() or qs.filter(zone="").first() or qs.first()

    if not project:
        raise ValueError("No active Code Engine project available")

    logger.info("Selected project [%s] for compute profile [%s]", project.project_name, compute_profile)
    return project
