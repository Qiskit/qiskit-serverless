"""Shared test helpers for tests/api/."""

from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job


def create_function_access_result(
    provider_name,
    function_title,
    permissions,
    business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
):
    """Return a FunctionAccessResult with a single entry for the given provider/function/permissions."""
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=business_model,
    )
    return FunctionAccessResult(use_legacy_authorization=False, functions=[entry])
