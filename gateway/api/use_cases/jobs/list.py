"""This module contains the usecase get_jos"""

from typing import List

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.model_managers.jobs import JobFilters
from core.models import Job, Program as Function


class JobsListUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    def execute(self, user: AbstractUser, filters: JobFilters) -> tuple[List[Job], int]:
        """
        Retrieve user jobs with optional filters and pagination.

        Returns:
            tuple[list[Job], int]: (jobs, total_count)
        """
        # ensure function exists if filtered
        if filters.function:
            function = Function.objects.get_function(
                function_title=filters.function,
                provider_name=filters.provider,
            )

            if not function:
                raise FunctionNotFoundException(function=filters.function)

        queryset, total = Job.objects.user_jobs_page(user=user, filters=filters)

        # the list serializer nests compute_profile_fk, so fetch it in the page query
        # rather than once per row. Applied here and not in user_jobs_page because
        # provider_list shares that manager method and does not serialize the profile.
        return list(queryset.select_related("compute_profile_fk")), total
