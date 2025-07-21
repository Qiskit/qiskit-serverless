import logging
from typing import List
from api.models import Job
from api.views.enums.type_filter import TypeFilter
from api.repositories.jobs import JobsRepository

logger = logging.getLogger("gateway.use_cases.get_jobs")


class GetJobsUseCase:
    """Use case for retrieving user jobs with optional filtering and pagination."""

    jobs_repository = JobsRepository()

    def __init__(self, user, limit: int, offset: int, filter_type: TypeFilter):
        self.user = user
        self.limit = limit
        self.offset = offset
        self.filter_type = filter_type
        self.filters = {
            TypeFilter.CATALOG: self._get_catalog_jobs,
            TypeFilter.SERVERLESS: self._get_serverless_jobs,
        }

    def execute(self) -> List[Job]:
        """
        Returns a paginated list of `Job` objects based on the `filter` query parameter.

        - If `filter=catalog`, returns jobs authored by the user with an existing provider.
        - If `filter=serverless`, returns jobs authored by the user without a provider.
        - Otherwise, returns all jobs authored by the user.

        Returns:
            QuerySet: A filtered queryset of `Job` objects ordered by creation date (descending).
        """
        has_to_filter = self.filter_type in self.filters
        if has_to_filter:
            query_set = self.filters[self.filter_type]()
        else:
            query_set = self.jobs_repository.get_user_jobs(self.user)

        return query_set

    def _get_catalog_jobs(self):
        return self.jobs_repository.get_user_jobs_with_provider(
            self.user, limit=self.limit, offset=self.offset
        )

    def _get_serverless_jobs(self):
        return self.jobs_repository.get_user_jobs_without_provider(
            self.user, limit=self.limit, offset=self.offset
        )
