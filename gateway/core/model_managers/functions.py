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
            permission: Platform permission constant (e.g. PLATFORM_PERMISSION_RUN).
                Required when accessible_functions is provided and use_legacy_authorization=False.
        """
        if accessible_functions is not None and not accessible_functions.use_legacy_authorization:
            filter_function_names = accessible_functions.get_functions_by_provider(permission)
            provider_criteria = Q()
            for pname, titles in filter_function_names.items():
                provider_criteria |= Q(provider__name=pname, title__in=titles)
            return self.filter(Q(author=author) | provider_criteria).distinct()

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
        return queryset.first()

    def get_function(
        self,
        function_title: str,
        provider_name: Optional[str] = None,
    ) -> Optional[Function]:
        """
        This method returns the specified function unconditionally.

        Args:
            function_title (str): title of the function
            provider_name (str | None): name of the provider owner of the function

        Returns:
            Program | None: returns the function if it exists
        """

        queryset = self.filter(title=function_title)

        if provider_name:
            queryset = queryset.provider_functions(provider_name)

        return queryset.first()

    def get_function_by_permission(  # pylint: disable=too-many-positional-arguments
        self,
        user: AbstractUser,
        function_title: str,
        provider_name: Optional[str],
        accessible_functions: Optional[FunctionAccessResult] = None,
        permission: Optional[str] = None,
        legacy_permission_name: Optional[str] = None,
    ) -> Optional[Function]:
        """
        Returns the specified function if the user is the author or has access.

        When provider_name is None, always returns the user's own function (no permission check).
        When accessible_functions is provided and use_legacy_authorization=False, checks if the
        function entry has the given permission. Otherwise falls back to Django groups.

        Args:
            user: Django user requesting access
            function_title: title of the function
            provider_name: provider name, or None for user functions
            accessible_functions: Result from FunctionAccessClient. When present and
                use_legacy_authorization=False, used for the permission check.
            permission: Platform permission constant (e.g. PLATFORM_PERMISSION_VIEW).
                Required when accessible_functions is provided and use_legacy_authorization=False.
            legacy_permission_name: Django permission codename (e.g. VIEW_PROGRAM_PERMISSION).
                Only used in the Django groups fallback path.

        Returns:
            Program | None: the function if the user has access, else None
        """
        if not provider_name:
            return self.user_functions(author=user).get_function(function_title)

        if accessible_functions is not None and not accessible_functions.use_legacy_authorization:
            entry = accessible_functions.get_function(provider_name, function_title)
            if entry is None or permission not in entry.permissions:
                return None
            return self.get_function(function_title, provider_name)

        # Fallback: Django groups
        return self.with_permission(
            author=user,
            legacy_permission_name=legacy_permission_name,
        ).get_function(function_title, provider_name)
