"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import Optional
from django.contrib.auth.models import AbstractUser

from api.utils import create_dynamic_dependencies_whitelist


logger = logging.getLogger("gateway.use_cases.authentication")


class AvailableDynamicDependenciesUseCase:  # pylint: disable=too-few-public-methods
    """
    This class will available dynamic dependencies.
    """

    def execute(self) -> Optional[type[AbstractUser]]:
        """
        Get the dependencies from the whitlist
        """
        return create_dynamic_dependencies_whitelist()
