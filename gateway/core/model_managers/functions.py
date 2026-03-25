"""Functions model manager."""

from __future__ import annotations
import logging
from typing import Optional, Self, TYPE_CHECKING

from django.db.models import Q, QuerySet
from django.contrib.auth.models import AbstractUser, Group

logger = logging.getLogger("gateway")

if TYPE_CHECKING:
    from core.models import Program as Function


class FunctionsQuerySet(QuerySet):
    """Functions query set to transform into a manager."""

    def with_permission(self, author: AbstractUser, permission_name: str) -> Self:
        """
        Returns all the functions available to the user. This means:
            - User functions where the user is the author
            - Provider functions with the permission specified

        Args:
            author: Django author from who retrieve the functions
            permission_name (str): name of the permission. Values accepted
            RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION

        Returns:
            List[Function]: all the functions available to the user
        """
        groups = Group.objects.filter(user=author, permissions__codename=permission_name)
        author_groups_with_permissions_criteria = Q(instances__in=groups)
        author_criteria = Q(author=author)

        result_queryset = self.filter(author_criteria | author_groups_with_permissions_criteria).distinct()

        count = result_queryset.count()
        logger.info("[%d] Functions found for author [%s]", count, author.id)

        return result_queryset

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

        count = result_queryset.count()
        logger.info("[%d] user Functions found for author [%s]", count, author.id)

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

    def get_function_by_permission(
        self,
        user,
        permission_name: str,
        function_title: str,
        provider_name: Optional[str],
    ) -> Optional[Function]:
        """
        This method returns the specified function if the user is
        the author of the function or it has a permission.

        Args:
            user: Django user of the function that wants to get it
            permission_name (str): name of the permission. Values accepted
            RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION
            function_title (str): title of the function
            provider_name (str | None): name of the provider owner of the function

        Returns:
            Program | None: returns the function if it exists
        """

        if provider_name:
            return self.with_permission(
                author=user,
                permission_name=permission_name,
            ).get_function(function_title, provider_name)

        return self.user_functions(author=user).get_function(function_title)
