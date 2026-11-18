"""Functions model manager."""

from __future__ import annotations
import logging
from typing import Optional, Self, TYPE_CHECKING

from django.db.models import Q, QuerySet
from django.contrib.auth.models import AbstractUser, Group

from core.domain.authorization.function_access_result import FunctionAccessResult

if TYPE_CHECKING:
    from core.models import Program as Function

logger = logging.getLogger("core.FunctionsQuerySet")


class FunctionsQuerySet(QuerySet):
    """Functions query set to transform into a manager."""

    def with_permission(
        self,
        author: AbstractUser,
        legacy_permission_name: Optional[str] = None,
        accessible_functions: Optional[FunctionAccessResult] = None,
        permission: Optional[str] = None,
    ) -> Self:
        """
        Returns all the functions available to the user:
          - User functions where the user is the author
          - Provider functions the instance has access to (via accessible_functions)
          - OR provider functions via Django groups (fallback when use_legacy_authorization=True)

        Args:
            author: Django author from who retrieve the functions
            legacy_permission_name: Django permission codename (e.g. RUN_PROGRAM_PERMISSION).
                Only used in the Django groups fallback path.
            accessible_functions: Result from FunctionAccessClient. When present and
                use_legacy_authorization=False, filters by its entries for the given permission.
            permission: Runtime API permission constant (e.g. PLATFORM_PERMISSION_RUN).
                Required when accessible_functions is provided and use_legacy_authorization=False.
        """
        if accessible_functions and not accessible_functions.use_legacy_authorization:
            # Runtime API /entitlements
            filter_function_names = accessible_functions.get_functions_by_provider(permission)
            # Custom functions (provider=None) are always visible
            # Provider functions are gated by instance permissions, even if the user is the author.
            # (The provider operations differ -- ownership grants those, see ProviderAccessPolicy.)
            author_criteria = Q(author=author, provider=None)
            provider_criteria = Q()
            for pname, titles in filter_function_names.items():
                provider_criteria |= Q(provider__name=pname, title__in=titles)
            combined = author_criteria | provider_criteria if provider_criteria else author_criteria
            return self.filter(combined).distinct()

        # Fallback: Django groups
        groups = Group.objects.filter(user=author, permissions__codename=legacy_permission_name)
        author_groups_with_permissions_criteria = Q(instances__in=groups)
        author_criteria = Q(author=author)
        return self.filter(author_criteria | author_groups_with_permissions_criteria).distinct()

    def user_functions(self, author: AbstractUser) -> Self:
        """
        Returns the user functions available to the user. This means:
          - User functions where the user is the author
          - Provider is None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program]: user functions available to the user
        """

        result_queryset = self.filter(author=author, provider=None)
        return result_queryset

    def provider_functions(self, provider_name: Optional[str] = None) -> Self:
        """
        Returns the provider functions. This means:
          - Provider is NOT None

        Returns:
            QuerySet: providers functions
        """

        if not provider_name:
            return self.exclude(provider=None)

        return self.filter(provider__name=provider_name)

    def get_user_function(self, author: AbstractUser, function_title: str) -> Optional[Function]:
        """
        This method returns the specified function without a provider.

        Args:
            author: Django author from who retrieve the functions
            function_title (str): title of the function

        Returns:
            Program | None: returns the function if it exists
        """

        queryset = self.user_functions(author).filter(title=function_title)
        return queryset.select_related("provider", "default_size").first()

    def get_function(self, function_title: str, provider_name: str) -> Optional[Function]:
        """
        This method returns the specified provider function unconditionally.
        Functions without a provider are looked up with get_user_function.

        Args:
            function_title (str): title of the function
            provider_name (str): name of the provider owner of the function

        Returns:
            Program | None: returns the function if it exists
        """

        queryset = self.filter(title=function_title, provider__name=provider_name)
        return queryset.select_related("provider", "default_size").first()
