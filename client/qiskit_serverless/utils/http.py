"""This file contains some helpers to work with the HTTP calls to the API."""

from typing import Dict, Optional, Union


def get_headers(
    token: str,
    instance: Optional[str] = None,
    channel: Optional[str] = None,
) -> Dict[str, Union[str, bytes]]:
    """
    Returns the headers to make the calls to the API

    Args:
        token: authorization token
        instance: IBM Cloud CRN

    Returns:
        Dict[str, Union[str, bytes]]: dict with the authentication headers
    """

    headers = {
        "Authorization": f"Bearer {token}",
    }
    if channel is not None:
        headers["Service-Channel"] = channel
    if instance is not None:
        headers["Service-CRN"] = instance

    return headers
