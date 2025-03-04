"""This file contains some helpers to work with the HTTP calls to the API."""

from typing import Dict, Optional


def get_headers(token: str, instance: Optional[str] = None) -> Dict[str, str]:
    """Returns the headers to make the calls to the API"""

    headers = {
        "Authorization": f"Bearer {token}",
    }
    if instance is not None:
        headers["Service-CRN"] = instance

    return headers
