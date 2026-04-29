"""FunctionAccessResult dataclass."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from api.domain.authorization.function_access_entry import FunctionAccessEntry


@dataclass
class FunctionAccessResult:
    """Result from the external function access client for a given instance CRN."""

    has_response: bool
    message: str
    functions: List[FunctionAccessEntry] = field(default_factory=list)

    def get_function(self, provider_name: str, function_title: str) -> Optional[FunctionAccessEntry]:
        """Return the entry matching provider_name and function_title, or None."""
        for entry in self.functions:
            if entry.provider_name == provider_name and entry.function_title == function_title:
                return entry
        return None

    def has_permission_for_function(self, provider_name: str, function_title: str, permission: str) -> bool:
        """Return True if the specific function has the permission."""
        entry = self.get_function(provider_name, function_title)
        return entry is not None and permission in entry.permissions

    def has_permission_for_provider(self, provider_name: str, permission: str) -> bool:
        """Return True if any function from the provider has the permission."""
        return any(e.provider_name == provider_name and permission in e.permissions for e in self.functions)

    def get_functions_by_provider(self, permission: str) -> Dict[str, Set[str]]:
        """Return function titles grouped by provider for entries that have the permission."""
        by_provider: Dict[str, Set[str]] = defaultdict(set)
        for e in self.functions:
            if permission in e.permissions:
                by_provider[e.provider_name].add(e.function_title)
        return dict(by_provider)

    def __str__(self) -> str:
        functions_str = ", ".join(f"{e.provider_name}.{e.function_title}" for e in self.functions)
        return f"FunctionAccessResult(has_response={self.has_response}, message={self.message!r}, functions=[{functions_str}])"
