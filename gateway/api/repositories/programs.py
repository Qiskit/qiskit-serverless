"""
Repository implementatio for Programs model
"""
import logging

from typing import Any, List

from django.db.models import Q
from django.contrib.auth.models import Group, Permission

from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Program


logger = logging.getLogger("gateway")


class ProgramRepository:
    """
    The main objective of this class is to manage the access to the model
    """

    def get_functions(self, author) -> List[Program] | Any:
        """
        Returns all the functions available to the user. This means:
          - User functions where the user is the author
          - Provider functions with view permissions

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program] | Any: all the functions available to the user
        """

        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        user_criteria = Q(user=author)
        view_permission_criteria = Q(permissions=view_program_permission)

        author_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )

        author_criteria = Q(author=author)
        author_groups_with_view_permissions_criteria = Q(
            instances__in=author_groups_with_view_permissions
        )

        result_queryset = Program.objects.filter(
            author_criteria | author_groups_with_view_permissions_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_functions(self, author) -> List[Program] | Any:
        """
        Returns the user functions available to the user. This means:
          - User functions where the user is the author
          - Provider is None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program] | Any: user functions available to the user
        """

        author_criteria = Q(author=author)
        provider_criteria = Q(provider=None)

        result_queryset = Program.objects.filter(
            author_criteria & provider_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] user Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_provider_functions_with_run_permissions(
        self, author
    ) -> List[Program] | Any:
        """
        Returns the user functions available to the user. This means:
          - Provider functions where the user has run permissions
          - Provider is NOT None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program] | Any: providers functions available to the user
        """

        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

        user_criteria = Q(user=author)
        run_permission_criteria = Q(permissions=run_program_permission)
        author_groups_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria
        )

        author_groups_with_run_permissions_criteria = Q(
            instances__in=author_groups_with_run_permissions
        )

        provider_exists_criteria = ~Q(provider=None)

        result_queryset = Program.objects.filter(
            author_groups_with_run_permissions_criteria & provider_exists_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] provider Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_function_by_title(self, author, title: str) -> Program | Any:
        """
        Returns the user function associated to a title:

        Args:
            author: Django author from who retrieve the function
            title: Title that the function must have to find it

        Returns:
            Program | Any: user function with the specific title
        """

        author_criteria = Q(author=author)
        title_criteria = Q(title=title)

        result_queryset = Program.objects.filter(
            author_criteria & title_criteria
        ).first()

        if result_queryset is None:
            logger.warning(
                "Function [%s] was not found or author [%s] doesn't have access to it",
                title,
                author.id,
            )

        return result_queryset

    def get_provider_function_by_title(
        self, author, title: str, provider_name: str
    ) -> Program | Any:
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
            Program | Any: provider function with the specific
                title and provider
        """

        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        user_criteria = Q(user=author)
        view_permission_criteria = Q(permissions=view_program_permission)

        author_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )

        author_criteria = Q(author=author)
        author_groups_with_view_permissions_criteria = Q(
            instances__in=author_groups_with_view_permissions
        )

        title_criteria = Q(title=title, provider__name=provider_name)

        result_queryset = Program.objects.filter(
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
