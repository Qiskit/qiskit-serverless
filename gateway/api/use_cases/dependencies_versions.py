"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import Dict
from packaging.requirements import Requirement

from api.utils import get_baked_dependencies

logger = logging.getLogger("api.AvailableDependenciesVersionsUseCase")


class AvailableDependenciesVersionsUseCase:
    """
    Return the dependencies baked into the runtime images (read-only discovery).
    """

    def execute(self) -> Dict[str, Requirement]:
        """
        Get the dependencies baked into the runtime images, so users can see what
        the image already ships and does not need to be brought themselves.
        """
        return get_baked_dependencies()
