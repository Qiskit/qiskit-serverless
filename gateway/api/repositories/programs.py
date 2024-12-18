"""
Repository implementation for Programs model
"""
import logging

from typing import List

from django.db.models import Q

from api.models import Program
from api.repositories.groups import GroupRepository


logger = logging.getLogger("gateway")


class ProgramRepository:
    """
    The main objective of this class is to manage the access to the model
    """

    # This repository should be in the use case implementatio
    # but this class is not ready yet so it will live here
    # in the meantime
    group_repository = GroupRepository()

    def get_functions_with_view_permissions(self, author) -> List[Program]:
        """
        Returns all the functions available to the user. This means:
          - User functions where the user is the author
          - Provider functions with view permissions

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program]: all the functions available to the user
        """

        view_groups = self.group_repository.get_groups_with_view_permissions_from_user(
            user=author
        )
        author_groups_with_view_permissions_criteria = Q(instances__in=view_groups)
        author_criteria = Q(author=author)

        result_queryset = Program.objects.filter(
            author_criteria | author_groups_with_view_permissions_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_functions(self, author) -> List[Program]:
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

        result_queryset = Program.objects.filter(
            author_criteria & provider_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] user Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_provider_functions_with_run_permissions(self, author) -> List[Program]:
        """
        Returns the provider functions available to the user. This means:
          - Provider functions where the user has run permissions
          - Provider is NOT None

        Args:
            author: Django author from who retrieve the functions

        Returns:
            List[Program]: providers functions available to the user
        """

        run_groups = self.group_repository.get_groups_with_run_permissions_from_user(
            user=author
        )
        author_groups_with_run_permissions_criteria = Q(instances__in=run_groups)
        provider_exists_criteria = ~Q(provider=None)

        result_queryset = Program.objects.filter(
            author_groups_with_run_permissions_criteria & provider_exists_criteria
        ).distinct()

        count = result_queryset.count()
        logger.info("[%d] provider Functions found for author [%s]", count, author.id)

        return result_queryset

    def get_user_function_by_title(self, author, title: str) -> Program | None:
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

    def get_provider_function_by_title_with_view_permissions(
        self, author, title: str, provider_name: str
    ) -> Program | None:
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
        view_groups = self.group_repository.get_groups_with_view_permissions_from_user(
            user=author
        )
        author_groups_with_view_permissions_criteria = Q(instances__in=view_groups)
        title_criteria = Q(title=title, provider__name=provider_name)

        result_queryset = Program.objects.filter(
            author_groups_with_view_permissions_criteria & title_criteria
        ).first()

        if result_queryset is None:
            logger.warning(
                "Function [%s/%s] was not found or author [%s] doesn't have access to it",
                provider_name,
                title,
                author.id,
            )

        return result_queryset

    def get_provider_function_by_title_with_run_permissions(
        self, author, title: str, provider_name: str
    ) -> Program | None:
        """
        Returns the provider function associated to:
          - A Function title
          - A Provider
          - Author must have run permission to execute it or be the author

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
        run_groups = self.group_repository.get_groups_with_run_permissions_from_user(
            user=author
        )
        author_groups_with_run_permissions_criteria = Q(instances__in=run_groups)
        title_criteria = Q(title=title, provider__name=provider_name)

        result_queryset = Program.objects.filter(
            author_groups_with_run_permissions_criteria & title_criteria
        ).first()

        if result_queryset is None:
            logger.warning(
                "Function [%s/%s] was not found or author [%s] doesn't have access to it",
                provider_name,
                title,
                author.id,
            )

        return result_queryset
