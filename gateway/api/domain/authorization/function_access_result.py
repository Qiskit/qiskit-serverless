"""FunctionAccessResult dataclass."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from api.domain.authorization.function_access_entry import FunctionAccessEntry


@dataclass
class FunctionAccessResult:
    """Result from the external function access client for a given instance CRN."""

    has_response: bool
    functions: List[FunctionAccessEntry] = field(default_factory=list)

    def get_function(self, provider_name: str, function_title: str) -> Optional[FunctionAccessEntry]:
        """Return the entry matching provider_name and function_title, or None."""
        for entry in self.functions:
            if entry.provider_name == provider_name and entry.function_title == function_title:
                return entry
        return None

    def has_action_for_provider(self, provider_name: str, action: str) -> bool:
        """Return True if any function of the given provider has the action."""
        return any(e.provider_name == provider_name and action in e.actions for e in self.functions)

    def get_functions_by_provider(self, action: str) -> Dict[str, Set[str]]:
        """Return function titles grouped by provider for entries that have the action."""
        by_provider: Dict[str, Set[str]] = defaultdict(set)
        for e in self.functions:
            if action in e.actions:
                by_provider[e.provider_name].add(e.function_title)
        return dict(by_provider)
