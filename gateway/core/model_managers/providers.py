"""Provider model manager."""

import logging
from typing import Optional, TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import Provider

logger = logging.getLogger("core.providers")


class ProviderQuerySet(QuerySet):
    """Provider query set to transform into a manager."""

    def get_by_name(self, name: str) -> Optional["Provider"]:
        """Return provider by name, logging a warning if not found."""
        provider = self.filter(name=name).first()
        if provider is None:
            logger.warning("Provider [%s] does not exist.", name)
        return provider
