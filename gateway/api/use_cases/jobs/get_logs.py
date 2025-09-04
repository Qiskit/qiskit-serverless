from django.contrib.auth.models import AbstractUser
from api.repositories.jobs import JobsRepository
from api.domain.exceptions.not_found_error import NotFoundError


class GetJobLogsUseCase:

    jobs_repository = JobsRepository()

    def execute(self, job_id: str, user: AbstractUser) -> str:

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
