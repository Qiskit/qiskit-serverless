"""Use case: set a Job's sub_status, with access control and safe retries."""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.forbidden_error import ForbiddenError
from api.domain.exceptions.not_found_error import NotFoundError
from api.models import Job, JobEvent
from api.repositories.jobs import JobsRepository
from core.utils import retry_function
from core.services.job_status import update_job_status
from api.model_managers.job_events import JobEventContext, JobEventOrigin

logger = logging.getLogger("gateway.use_cases.jobs")


class SetJobSubStatusUseCase:
    """Set a job's sub_status if the user can and the job is RUNNING."""

    jobs_repository = JobsRepository()

    def execute(self, job_id: UUID, user: AbstractUser, sub_status: str) -> Job:
        """
        Update the sub_status of a job.

        Args:
            job_id: Target Job ID.
            user: Requesting user.
            sub_status: New sub_status value.

        Returns:
            The updated Job.

        Raises:
            NotFoundError: If the job does not exist or access is denied.
            ForbiddenError: If the job is not in RUNNING status.
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        can_update_sub_status = JobAccessPolicies.can_update_sub_status(user, job)
        if not can_update_sub_status:
            raise NotFoundError(f"Job [{job_id}] not found")

        status_has_changed = update_job_status(job)

        if job.status != Job.RUNNING:
            warning_msg = (
                "'sub_status' cannot change because the job"
                " [%s] current status is not Running",
                job.id,
            )

            logger.warning(warning_msg)
            raise ForbiddenError(
                "Cannot update 'sub_status' when is not"
                f" in RUNNING status. (Currently {job.status})"
            )

        def set_sub_status():
            self.jobs_repository.update_job_sub_status(job, sub_status)
            job.refresh_from_db()

        old_sub_status = job.sub_status

        retry_function(
            callback=set_sub_status,
            error_message=f"Job[{job_id}] record has not been updated due to lock.",
            error_message_level=logging.WARNING,
        )

        if status_has_changed or old_sub_status != job.sub_status:
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.API,
                context=JobEventContext.SET_SUB_STATUS,
                status=job.status,
                sub_status=job.sub_status,
            )

        return job
