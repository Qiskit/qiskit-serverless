"""FunctionAccessResult dataclass."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core.domain.authorization.function_access_entry import FunctionAccessEntry


class FunctionAccessResult:
    """Result from the external function access client for a given instance CRN."""

    has_response: bool
    functions: List[FunctionAccessEntry]

    def get_function(self, provider_name: str, function_title: str) -> Optional[FunctionAccessEntry]:
        """Return the entry matching provider_name and function_title, or None."""
        for entry in self.functions:
            if entry.provider_name == provider_name and entry.function_title == function_title:
                return entry
        return None

    def has_permission_for_provider(self, provider_name: str, permission: str) -> bool:
        """Return True if any function of the given provider has the permission."""
        return any(e.provider_name == provider_name and permission in e.permissions for e in self.functions)

    def get_functions_by_provider(self, permission: str) -> Dict[str, Set[str]]:
        """Return function titles grouped by provider for entries that have the permission."""
        by_provider: Dict[str, Set[str]] = defaultdict(set)
        for e in self.functions:
            if permission in e.permissions:
                by_provider[e.provider_name].add(e.function_title)
        return dict(by_provider)
