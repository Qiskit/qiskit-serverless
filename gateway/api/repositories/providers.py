"""
Repository implementation for Provider model
"""
import logging

from api.models import Provider


logger = logging.getLogger("gateway")


class ProviderRepository:  # pylint: disable=too-few-public-methods
    """
    The main objective of this class is to manage the access to the model
    """

    def get_provider_by_name(self, name: str) -> Provider | None:
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
