"""
RuntimeJob repository
"""
from api.models import RuntimeJob


class RuntimeJobRepository:
    """
    RuntimeJob repository
    """

    def get_runtime_job(self, job) -> RuntimeJob:
        """get runtime job for job"""
        return RuntimeJob.objects.filter(job=job)
    

    def create_runtime_job(self, job, runtime_job_id: str, runtime_session: str | None) -> RuntimeJob:
            """Create a runtime job associated with a given job"""
            return RuntimeJob.objects.create(
                job=job,
                runtime_job=runtime_job_id,
                runtime_session=runtime_session,
            )

