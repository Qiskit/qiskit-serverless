"""Return type for result retrieval use cases."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GetResultResponse:
    """Discriminated result from result use cases.

    Exactly one of raw_result or redirect_url will be set, or neither (Fleet, not ready yet).
    """

    raw_result: Optional[str] = field(default=None)
    redirect_url: Optional[str] = field(default=None)

    def __post_init__(self):
        if self.raw_result is not None and self.redirect_url is not None:
            raise ValueError("Cannot set both raw_result and redirect_url")
