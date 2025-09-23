"""
utilities for API.
"""

from drf_yasg import openapi
from rest_framework import status


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
