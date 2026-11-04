"""Authentication use case to manage the authentication process in the api."""

import logging
from typing import Dict
from packaging.requirements import Requirement

from api.utils import get_image_dependencies

logger = logging.getLogger("api.AvailableDependenciesVersionsUseCase")


class AvailableDependenciesVersionsUseCase:
    """
    Return the dependencies shipped in the runtime images (read-only discovery).
    """

    def execute(self) -> Dict[str, Requirement]:
        """
        Get the dependencies shipped in the runtime images, so users can see what
        the image already ships and does not need to be brought themselves.
        """
        return get_image_dependencies()
