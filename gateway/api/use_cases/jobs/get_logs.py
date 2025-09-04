from django.contrib.auth.models import AbstractUser
from api.repositories.jobs import JobsRepository
from api.domain.exceptions.not_found_error import NotFoundError


class GetJobLogsUseCase:
    """Use case for retrieving job logs."""

    jobs_repository = JobsRepository()

    def execute(self, job_id: str, user: AbstractUser) -> str:
        """Return the logs of a job if the user has access.

        Args:
            job_id (str): Unique identifier of the job.
            user (AbstractUser): User requesting the logs.

        Raises:
            NotFoundError: If the job does not exist.

        Returns:
            str: Job logs if accessible, otherwise a message indicating no logs are available.
        """
        job = self.jobs_repository.get_job_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Job [{job_id}] not found")

        if job.program and job.program.provider:
            provider_groups = set(job.program.provider.admin_groups.all())
            user_groups = set(user.groups.all())
            if provider_groups & user_groups:
                return job.logs
            return "No available logs"

        if user == job.author:
            return job.logs
        return "No available logs"
