"""FunctionAccessEntry dataclass."""

import logging
from dataclasses import dataclass
from typing import Set

from core.models import Job

logger = logging.getLogger("api.FunctionAccessEntry")

VALID_BUSINESS_MODELS = {
    Job.BUSINESS_MODEL_TRIAL,
    Job.BUSINESS_MODEL_SUBSIDIZED,
    Job.BUSINESS_MODEL_CONSUMPTION,
}


@dataclass
class FunctionAccessEntry:
    """Represents a single function accessible to an instance, with its allowed actions."""

    provider_name: str
    function_title: str
    actions: Set[str]
    business_model: str

    def __post_init__(self):
        if self.business_model not in VALID_BUSINESS_MODELS:
            logger.error(
                "Invalid business_model '%s' for %s.%s. Valid: %s",
                self.business_model,
                self.provider_name,
                self.function_title,
                VALID_BUSINESS_MODELS,
            )
            raise ValueError(
                f"Invalid business_model '{self.business_model}' " f"for {self.provider_name}.{self.function_title}"
            )
