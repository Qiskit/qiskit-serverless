"""
utilities for API.
"""

from urllib.parse import urlencode
from typing import List, Optional, Any, TypedDict

import magic

from rest_framework.exceptions import ValidationError
from django.core.files import File
from django.conf import settings


class PaginatedResponse(TypedDict):
    """
    Standard paginated response structure for API endpoints.

    Attributes:
        count: Total number of items (before pagination)
        next: URL for the next page of results, None if no next page
        previous: URL for the previous page of results, None if no previous page
        results: List of items for the current page
    """

    count: int
    next: Optional[str]
    previous: Optional[str]
    results: List[Any]


def create_paginated_response(
    data: List[Any],
    total_count: int,
    request,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> PaginatedResponse:
    """
    Creates a standard paginated response for API endpoints.

    Args:
        data: List of serialized data
        total_count: Total number of items
        request: Django request object
        limit: Maximum number of items per page
        offset: Number of items to skip

    Returns:
        PaginatedResponse with the standard pagination structure
    """
    response_data: PaginatedResponse = {
        "count": total_count,
        "next": None,
        "previous": None,
        "results": data,
    }

    if limit is None:
        return response_data

    offset = offset or 0
    base_url = request.build_absolute_uri(request.path)

    # Calculate next URL
    if offset + limit < total_count:
        next_params = {"limit": limit, "offset": offset + limit}
        response_data["next"] = f"{base_url}?{urlencode(next_params)}"

    # Calculate previous URL
    if offset > 0:
        prev_params = {"limit": limit, "offset": max(0, offset - limit)}
        response_data["previous"] = f"{base_url}?{urlencode(prev_params)}"

    return response_data


def parse_positive_int(param: str, default: int) -> int:
    """
    Convert a string parameter to a non-negative integer.

    Args:
        param (str): String value to parse. If falsy, the default is used.
        default (int): Default value if param is None or empty.

    Returns:
        int: The parsed non-negative integer.

    Raises:
        ValueError: If the parsed value is negative or not a valid integer.
    """
    value = int(param or default)
    if value < 0:
        raise ValueError(f"{param} must be non-negative")
    return value


def validate_uploaded_file(file: File):
    """
    Checks that an uploaded file has a valid mime type.

    Args:
        file (File): The uploaded file

    Raises:
        ValidationError: If the file is not a valid type
    """

    if not file:
        raise ValidationError("A file should be uploaded.")

    mime = magic.from_buffer(file.read(2048), mime=True)
    file.seek(0)

    if not mime in settings.UPLOAD_FILE_VALID_MIME_TYPES:
        raise ValidationError("Uploaded file is not a valid type.")
