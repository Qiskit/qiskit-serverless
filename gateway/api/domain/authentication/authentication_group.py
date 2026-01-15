"""
Class used by the authentication process to store the information of
the groups from 3rd party services.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class AuthenticationGroup:
    """AuthenticationGroup."""

    group_name: str
    account: Optional[str] = None
