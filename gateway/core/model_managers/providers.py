"""Provider model manager."""

import logging
from typing import Optional, TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import Provider

logger = logging.getLogger("api.ProviderRepository")


class ProviderQuerySet(QuerySet):
    """Provider query set to transform into a manager."""

    def get_by_name(self, name: str) -> Optional["Provider"]:
        provider = self.filter(name=name).first()
        if provider is None:
            logger.warning("Provider [%s] does not exist.", name)
        return provider
