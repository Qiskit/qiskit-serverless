"""
Custom Authentication DRF class to store the authentication information of a user in the request.
"""

from dataclasses import dataclass
from typing import Optional

from api.domain.authentication.channel import Channel


@dataclass
class CustomAuthentication:
    """CustomAuthentication."""

    channel: Channel
    token: str
    instance: Optional[str]
