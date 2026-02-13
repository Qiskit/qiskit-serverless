"""
Repository implementation for Provider model
"""

import logging
from typing import List, Optional
from django.contrib.auth.models import Group

from core.models import Provider

logger = logging.getLogger("gateway")


class ProviderRepository:
    """
    The main objective of this class is to manage the access to the model
    """

    def get_provider_by_name(self, name: str) -> Optional[Provider]:
        """
        Returns the provider associated with a name.

        Args:
          - name: provider name

        Returns:
          - Provider | None: returns the specific provider if it exists
        """

        provider = Provider.objects.filter(name=name).first()
        if provider is None:
            logger.warning("Provider [%s] does not exist.", name)

        return provider

    def get_or_create_by_name(
        self, name: str, registry: str, admin_groups: List[Group]
    ) -> Optional[Provider]:
        """
        Creates a new provider with a given name and registry.

        Args:
          - name: provider name
          - registry: reference to the registry that the provider
          will have access
          - admin_groups: groups that will work as admin

        Returns:
          - Provider | None: returns the new Provider
        """

        provider, created = Provider.objects.get_or_create(
            name=name,
            registry=registry,
        )
        if created:
            for admin_group in admin_groups:
                provider.admin_groups.add(admin_group)

        return provider
