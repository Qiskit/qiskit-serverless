"""
utilities for API.
"""

from urllib.parse import urlencode
from typing import List, Optional, Any, TypedDict
from drf_yasg import openapi
from rest_framework import status, serializers

from api.utils import sanitize_name


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


def error_schema(example_msg: str, description: str = "Error response"):
    """
    Openapi reuse utility
    """
    return openapi.Response(
        description=description,
        schema=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "message": openapi.Schema(type=openapi.TYPE_STRING, example=example_msg)
            },
            required=["message"],
        ),
    )


def standard_error_responses(
    bad_request_example: str | None = None,
    forbidden_example: str | None = None,
    not_found_example: str | None = None,
    conflict_example: str | None = None,
    unauthorized_example: str | None = None,
):
    """
    Utility to generate standard error documentation
    """
    responses = {}
    if bad_request_example:
        responses[status.HTTP_400_BAD_REQUEST] = error_schema(
            bad_request_example, "Invalid input."
        )
    if unauthorized_example:
        responses[status.HTTP_401_UNAUTHORIZED] = error_schema(
            unauthorized_example, "Authentication required."
        )
    if forbidden_example:
        responses[status.HTTP_403_FORBIDDEN] = error_schema(
            forbidden_example, "Not allowed to perform this action."
        )
    if not_found_example:
        responses[status.HTTP_404_NOT_FOUND] = error_schema(
            not_found_example, "Resource not found."
        )
    if conflict_example:
        responses[status.HTTP_409_CONFLICT] = error_schema(
            conflict_example, "Conflict."
        )
    return responses


class SanitizedCharField(serializers.CharField):
    """CharField that applies sanitize_name to its value."""

    def to_internal_value(self, data):
        """Method to sanitize the field"""
        value = super().to_internal_value(data)
        return sanitize_name(value) if value else None
