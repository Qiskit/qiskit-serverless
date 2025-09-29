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
