"""Job model manager."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Tuple, Self

from django.db.models import QuerySet
from django.contrib.auth.models import AbstractUser

from core.enums.type_filter import TypeFilter

logger = logging.getLogger("gateway")


@dataclass(slots=True)
class JobFilters:
    """
    Filters for Job queries.

    Attributes:
        function: Function title
        functions: Function title list
        provider: Provider who owns the function
        limit: Number of results to return per page
        offset: Number of results to skip
        type: Type of job to filter
        status: Current job status
        created_after: Filter jobs created after this date
    """

    function: Optional[str] = None
    functions: Optional[Set[str]] = None
    provider: Optional[str] = None

    limit: Optional[int] = None
    offset: Optional[int] = None
    filter: Optional[TypeFilter] = None
    status: Optional[str] = None
    created_after: Optional[datetime] = None


class JobQuerySet(QuerySet):
    """Job events query set to transform into a manager."""

    def user_jobs_page(
        self,
        user: AbstractUser,
        filters: Optional[JobFilters],
        ordering: str = "-created",
    ) -> Tuple[Self, int]:
        """
        Get user jobs with optional filters and pagination.

        Args:
            filters: Optional filters to apply
            limit: Max number of results
            offset: Number of results to skip
            ordering: Field to order by. Default: -created (newest first)

        Returns:
            (queryset, total_count): Filtered results and total count
        """
        queryset = self.order_by(ordering)

        if user:
            queryset = queryset.filter(author=user)

        limit = 20
        offset = 0
        if filters:
            queryset = queryset._apply_filters(filters)  # pylint: disable=protected-access
            limit = filters.limit
            offset = filters.offset

        return queryset._paginate_queryset(limit, offset)  # pylint: disable=protected-access

    def _apply_filters(
        self,
        filters: JobFilters,
    ) -> Self:
        """Apply filters to job queryset."""

        queryset = self

        match filters.filter:
            case TypeFilter.CATALOG:
                if filters.provider:
                    queryset = queryset.filter(program__provider=filters.provider)
                else:
                    queryset = queryset.exclude(program__provider=None)
            case TypeFilter.SERVERLESS:
                queryset = queryset.filter(program__provider=None)

        if filters.status:
            queryset = queryset.filter(status=filters.status)

        if filters.created_after:
            queryset = queryset.filter(created__gte=filters.created_after)

        if filters.function:
            queryset = queryset.filter(program__title=filters.function)
        elif filters.functions:
            queryset = queryset.filter(program__title__in=filters.functions)

        return queryset

    def _paginate_queryset(self, limit: int | None, offset: int | None) -> tuple[Self, int]:
        """Apply pagination to job queryset."""
        total_count = self.count()

        start = offset or 0
        end = start + limit if limit else None

        if start >= total_count > 0:
            return self.none(), total_count

        return self[start:end], total_count
