"""AuthenticationResult dataclass."""

from dataclasses import dataclass
from typing import Optional

from django.contrib.auth.models import AbstractUser


@dataclass
class AuthenticationResult:
    """Result of the authentication flow for the api.

    Carries the authenticated user together with the IBM Cloud instance
    attributes resolved during authentication. They are grouped in a dataclass
    instead of a tuple because they are all optional strings and positional
    ordering would be easy to get wrong.
    """

    user: Optional[type[AbstractUser]]
    account_id: Optional[str]
    plan_id: Optional[str]
    subscription_id: Optional[str]
