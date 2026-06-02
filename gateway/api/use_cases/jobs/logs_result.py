"""Return type for log retrieval use cases."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LogsResult:
    """Discriminated result from log use cases.

    Exactly one of raw_log or redirect_url will be set, or neither (no logs yet).
    """

    raw_log: Optional[str] = field(default=None)
    redirect_url: Optional[str] = field(default=None)
