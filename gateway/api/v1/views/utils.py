"""
utilities for API.
"""

from urllib.parse import urlencode
from typing import List, Optional, Any, TypedDict


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
