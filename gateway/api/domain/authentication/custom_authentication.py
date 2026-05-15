"""
Custom Authentication DRF class to store the authentication information of a user in the request.
"""

from dataclasses import dataclass
from typing import Optional

from api.domain.authentication.channel import Channel
from core.domain.authorization.function_access_result import FunctionAccessResult


@dataclass
class CustomAuthentication:
    """CustomAuthentication."""

    channel: Channel
    token: str
    accessible_functions: FunctionAccessResult
    instance: Optional[str]
    account_id: Optional[str]
