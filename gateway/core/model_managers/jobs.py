"""Job model manager."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Set, Tuple, Self

from django.db.models.functions import Coalesce, NullIf
from django.db.models import OuterRef, QuerySet, Subquery, Value
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


UNASSIGNED_PROJECT = "unassigned"


class JobQuerySet(QuerySet):
    """Job events query set to transform into a manager."""

    def with_program(self) -> Self:
        """Fetch the job's program and its provider in the same query."""
        return self.select_related("program__provider")

    def with_scheduler_context(self) -> Self:
        """Join the author, program, provider, Code Engine project and config that the scheduler reads."""
        return self.select_related("author", "program__provider", "program__code_engine_project", "config")

    def with_event_times(self) -> Self:
        """Load two event times with each job, so a loop does not query them per job. Read them with the
        ``Job.last_event_at`` (timeout) and ``Job.first_running_at`` (usage) properties, which raise without this.

        The values are as of the query: an event written later in the same pass is not in them.
        """
        from core.models import JobEvent  # pylint: disable=import-outside-toplevel, cyclic-import

        events = JobEvent.objects.filter(job=OuterRef("pk"))
        # Underscored: a property and an annotation cannot share a name, Django would fail to set it
        return self.annotate(
            _last_event_at=Subquery(events.order_by("-created").values("created")[:1]),
            _first_running_at=Subquery(events.running_status_events().values("created")[:1]),
        )

    def held_fleets(self) -> Self:
        """Fleets jobs whose Code Engine fleet we have not deleted: a fleet_id and no stamp."""
        from core.models import Program  # pylint: disable=import-outside-toplevel, cyclic-import

        return self.filter(runner=Program.FLEETS, fleet_id__isnull=False, fleet_deleted_at__isnull=True)

    def with_fleet_project(self) -> Self:
        """Annotate ``fleet_project_sql``, the SQL form of ``Job.fleet_project``."""
        return self.annotate(
            fleet_project_sql=Coalesce(NullIf("ce_project_name", Value("")), Value(UNASSIGNED_PROJECT))
        )

    def with_fleet_region(self) -> Self:
        """Annotate ``fleet_region_sql``, the SQL form of ``Job.fleet_region``. Not in held_fleets, for its index."""
        return self.annotate(
            fleet_region_sql=Coalesce(NullIf("ce_region", Value("")), "program__code_engine_project__region")
        )

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
                queryset = queryset.exclude(program__provider=None)
            case TypeFilter.SERVERLESS:
                queryset = queryset.filter(program__provider=None)

        if filters.provider:
            queryset = queryset.filter(program__provider__name=filters.provider)

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
