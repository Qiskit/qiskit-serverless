"""
This file stores the logic to manage the access to data stores
"""
import os

from django.conf import settings

from utils import sanitize_file_path

USER_STORAGE = "user"
PROVIDER_STORAGE = "provider"


def get_user_path(username: str, function_name: str, provider_name: str | None) -> str:
    """
    This method returns the path where the user will store its files
    """
    if provider_name is None:
        path = username
    else:
        path = f"{username}/{provider_name}/{function_name}"
    return os.path.join(
        sanitize_file_path(settings.MEDIA_ROOT),
        sanitize_file_path(path),
    )


def get_provider_path(function_name: str, provider_name: str) -> str:
    """
    This method returns the provider path where the user will store its files
    """
    path = f"{provider_name}/{function_name}"
    return os.path.join(
        sanitize_file_path(settings.MEDIA_ROOT),
        sanitize_file_path(path),
    )
