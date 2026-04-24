"""FunctionAccessClient."""

from api.domain.authorization.function_access_result import FunctionAccessResult


class FunctionAccessClient:
    """Client for retrieving accessible functions for a given instance CRN."""

    def get_accessible_functions(self, instance_crn: str) -> FunctionAccessResult:
        """Return all functions accessible to the given instance CRN with their actions."""
        raise NotImplementedError
