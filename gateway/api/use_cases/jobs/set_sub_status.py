import logging
from django.contrib.auth.models import AbstractUser
from api.models import Job
from api.utils import retry_function
from api.repositories.jobs import JobsRepository
from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.forbidden_error import ForbiddenError

logger = logging.getLogger("gateway.use_cases.jobs")


class SetJobSubStatusUseCase:

    jobs_repository = JobsRepository()

    def execute(self, job_id: str, user: AbstractUser, sub_status: str) -> Job:

        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        can_update_sub_status = JobAccessPolicies.can_update_sub_status(user, job)
        if not can_update_sub_status:
            raise NotFoundError(f"Job [{job_id}] not found")

        def set_sub_status():
            # If we import this with the regular imports,
            # update jobs statuses test command fail.
            # it should be something related with python import order.
            from api.management.commands.update_jobs_statuses import (  # pylint: disable=import-outside-toplevel
                update_job_status,
            )

            update_job_status(job)

            if job.status != Job.RUNNING:
                logger.warning(
                    "'sub_status' cannot change because the job"
                    " [%s] current status is not Running",
                    job.id,
                )
                raise ForbiddenError(
                    "Cannot update 'sub_status' when is not"
                    f" in RUNNING status. (Currently {job.status})"
                )

            self.jobs_repository.update_job_sub_status(job, sub_status)
            return self.jobs_repository.get_job_by_id(job_id)

        job = retry_function(
            callback=set_sub_status,
            error_message=f"Job[{job_id}] record has not been updated due to lock.",
            error_message_level=logging.WARNING,
        )

        return job
