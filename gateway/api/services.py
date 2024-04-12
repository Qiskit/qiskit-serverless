"""
Services for api application:
    - Program Service
    - Job Service

Version services inherit from the different services.
"""

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code
# Disable duplicate code due to refactorization. This file will be delited.

import logging
import json

from .models import Program, JobConfig, Job
from .exceptions import InternalServerErrorException
from .utils import encrypt_env_vars, build_env_variables

logger = logging.getLogger("gateway.services")


class JobService:
    """
    Job service allocate the logic related with a job
    """

    @staticmethod
    def save(
        program: Program,
        arguments: str,
        author,
        jobconfig: JobConfig,
        token: str,
        carrier,
        status=Job.QUEUED,
    ) -> Job:
        """
        Creates or updates a job

        Args:
            program: instance of a Program
            arguments: arguments from the serializer
            author: author from the request
            jobconfig: instance of a JobConfig
            token: token from the request after being decoded
            carrier: object injected from TraceContextTextMapPropagator
            status: status of the job, QUEUED by default

        Returns:
            Job instance
        """

        job = Job(
            program=program,
            arguments=arguments,
            author=author,
            status=status,
            config=jobconfig,
        )
        env = encrypt_env_vars(build_env_variables(token, job, arguments))
        try:
            env["traceparent"] = carrier["traceparent"]
        except KeyError:
            pass

        try:
            job.env_vars = json.dumps(env)
            job.save()
        except (Exception) as save_job_exception:
            logger.error(
                "Exception was caught saving the Job[%s]. \n Error trace: %s",
                job.id,
                save_job_exception,
            )
            raise InternalServerErrorException(
                "Unexpected error saving the environment variables of the job"
            ) from save_job_exception

        return job
