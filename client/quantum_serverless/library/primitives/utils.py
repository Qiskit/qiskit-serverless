"""Utils."""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class SessionParameters:
    """SessionParameters."""

    active_account: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    max_time: Optional[int] = None
