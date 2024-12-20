"""
Repository implementation for Programs model
"""
import logging

from typing import List

from django.db.models import Q

from api.models import (
    RUN_PROGRAM_PERMISSION,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)
from api.repositories.users import UserRepository


logger = logging.getLogger("gateway")


class FunctionRepository:
    """
    The main objective of this class is to manage the access to the model
    """

    # This repository should be in the use case implementation
    # but this class is not ready yet so it will live here
    # in the meantime
    user_repository = UserRepository()

    def get_functions_with_view_permissions(self, author) -> List[Function]:
        """
        Returns all the functions available to the user. This means:
          - User functions where the user is the author
          - Provider functions with view permissions

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Function]: all the functions available to the user
        """

        view_groups = self.user_repository.get_groups_by_permissions(
            user=author, permission_name=VIEW_PROGRAM_PERMISSION
        )
        author_groups_with_view_permissions_criteria = Q(instances__in=view_groups)
        author_criteria = Q(author=author)

        result_queryset = Function.objects.filter(
            author_criteria | author_groups_with_view_permissions_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_functions(self, author) -> List[Function]:
        """
        Returns the user functions available to the user. This means:
          - User functions where the user is the author
          - Provider is None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program]: user functions available to the user
        """

        author_criteria = Q(author=author)
        provider_criteria = Q(provider=None)

        result_queryset = Function.objects.filter(
            author_criteria & provider_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] user Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_provider_functions_with_run_permissions(self, author) -> List[Function]:
        """
        Returns the provider functions available to the user. This means:
          - Provider functions where the user has run permissions
          - Provider is NOT None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program]: providers functions available to the user
        """

        run_groups = self.user_repository.get_groups_by_permissions(
            user=author, permission_name=RUN_PROGRAM_PERMISSION
        )
        author_groups_with_run_permissions_criteria = Q(instances__in=run_groups)
        provider_exists_criteria = ~Q(provider=None)

        result_queryset = Function.objects.filter(
            author_groups_with_run_permissions_criteria & provider_exists_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] provider Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_function(self, author, title: str) -> Function | None:
        """
        Returns the user function associated to a title:

        Args:
            author: Django author from who retrieve the function
            title: Title that the function must have to find it

        Returns:
            Program | None: user function with the specific title
        """

        author_criteria = Q(author=author)
        title_criteria = Q(title=title)

        result_queryset = Function.objects.filter(
            author_criteria & title_criteria
        ).first()

        if result_queryset is None:
            logger.warning(
                "Function [%s] was not found or author [%s] doesn't have access to it",
                title,
                author.id,
            )

        return result_queryset

    def get_provider_function_by_permission(
        self, author, permission_name: str, title: str, provider_name: str
    ) -> Function | None:
        """
        Returns the provider function associated to:
          - A Function title
          - A Provider
          - Author must have view permission to see it or be the author

        Args:
            author: Django author from who retrieve the function
            title: Title that the function must have to find it
            provider: Provider associated to the function

        Returns:
            Program | None: provider function with the specific
                title and provider
        """

        # This access should be checked in the use-case but how we don't
        # have it implemented yet we will do the check by now in the
        # repository call
        view_groups = self.user_repository.get_groups_by_permissions(
            user=author, permission_name=permission_name
        )
        author_groups_with_view_permissions_criteria = Q(instances__in=view_groups)
        author_criteria = Q(author=author)
        title_criteria = Q(title=title, provider__name=provider_name)

        result_queryset = Function.objects.filter(
            (author_criteria | author_groups_with_view_permissions_criteria)
            & title_criteria
        ).first()

        if result_queryset is None:
            logger.warning(
                "Function [%s/%s] was not found or author [%s] doesn't have access to it",
                provider_name,
                title,
                author.id,
            )

        return result_queryset

    def get_function_by_permission(
        self,
        user,
        permission_name: str,
        function_title: str,
        provider_name: str | None,
    ) -> None:
        """
        This method returns the specified function if the user is
        the author of the function or it has run permissions.

        Args:
            user: Django user of the function that wants to get it
            function_title (str): title of the function
            provider_name (str | None): name of the provider owner of the function

        Returns:
            Program | None: returns the function if it exists
        """

        if provider_name:
            return self.get_provider_function_by_permission(
                author=user,
                permission_name=permission_name,
                title=function_title,
                provider_name=provider_name,
            )

        return self.get_user_function(author=user, title=function_title)
