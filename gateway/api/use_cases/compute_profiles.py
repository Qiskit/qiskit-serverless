"""Use case: list the compute profiles registered on this deployment."""

import logging

from django.db.models import QuerySet

from core.models import ComputeProfile

logger = logging.getLogger("api.ComputeProfilesUseCase")


class ComputeProfilesUseCase:
    """Return the registered compute-profile catalog.

    These are the ``ComputeProfile`` rows an uploader may name (by ``compute_profile_id``)
    in a function's ``sizes_map``. Read-only; ordered for a deterministic listing.
    """

    def execute(self) -> QuerySet:
        """Get every registered compute profile, ordered by identifier."""
        return ComputeProfile.objects.all().order_by("compute_profile_id")
