"""Use case: set a Job's sub_status, with access control and safe retries."""

import logging
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from core.models import Job, JobEvent
from core.model_managers.job_events import JobEventContext, JobEventOrigin

logger = logging.getLogger("gateway.use_cases.jobs")


class SetJobSubStatusUseCase:
    """Set a job's sub_status if the user can and the job is RUNNING."""

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
            JobNotFoundException: If the job does not exist or access is denied.
            ForbiddenError: If the job is not in RUNNING status.
        """
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist:
            raise JobNotFoundException(str(job_id))

        can_update_sub_status = JobAccessPolicies.can_update_sub_status(user, job)
        if not can_update_sub_status:
            raise JobNotFoundException(str(job_id))

        # update sub status in PENDING and RUNNING is allowed
        # we accept that we could have SET_SUB_STATUS events before RUNNING
        updated = Job.objects.filter(id=job.id, status__in=Job.RUNNING_STATUSES).update(sub_status=sub_status)

        if not updated:
            logger.warning(
                "[set-sub-status] job_id=%s user_id=%s status=%s | Sub-status update rejected (not PENDING/RUNNING)",
                job.id,
                user.id,
                job.status,
            )
            raise InvalidAccessException(
                "Cannot update 'sub_status' when is not" f" in PENDING/RUNNING status. (Currently {job.status})"
            )

        if job.sub_status != sub_status:
            job.sub_status = sub_status
            JobEvent.objects.add_sub_status_event(
                job_id=job.id,
                origin=JobEventOrigin.API,
                context=JobEventContext.SET_SUB_STATUS,
                sub_status=sub_status,
            )
            logger.info(
                "[set-sub-status] job_id=%s user_id=%s sub_status=%s | Sub-status updated ok",
                job.id,
                user.id,
                job.sub_status,
            )

        return job
