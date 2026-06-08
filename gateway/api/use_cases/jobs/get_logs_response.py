"""Return type for log retrieval use cases."""

from dataclasses import dataclass, field


@dataclass
class GetLogsResponse:
    """Discriminated result from log use cases.

    Exactly one of raw_log or redirect_url will be set, or neither (no logs yet).
    """

    raw_log: str | None = field(default=None)
    redirect_url: str | None = field(default=None)

    def __post_init__(self):
        if self.raw_log is not None and self.redirect_url is not None:
            raise ValueError("Cannot set both raw_log and redirect_url")
