"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import Dict
from pkg_resources import Requirement

from api.utils import create_dynamic_dependencies_whitelist


logger = logging.getLogger("gateway.use_cases.dependencies_versions")


class AvailableDependenciesVersionsUseCase:
    """
    This class will return available dynamic dependencies on execute.
    """

    def execute(self) -> Dict[str, Requirement]:
        """
        Get the dependencies from the whitlist
        """
        return create_dynamic_dependencies_whitelist()
