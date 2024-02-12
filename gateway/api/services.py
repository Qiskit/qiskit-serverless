"""
Services for api application:
    - Program Service
    - Job Service

Version services inherit from the different services.
"""

# pylint: disable=too-few-public-methods

import logging
import json

from .models import Program, JobConfig, Job
from .exceptions import InternalServerErrorException, ResourceNotFoundException
from .utils import encrypt_env_vars, build_env_variables

logger = logging.getLogger("gateway.services")


class ProgramService:
    """
    Program service allocate the logic related with programs
    """

    @staticmethod
    def save(serializer, author, artifact) -> Program:
        """
        Save method gets a program serializer and creates or updates a program

        Args:
            serializer: django program model serializer
            author: user tipically got it from request
            artifact: file that is going to be run

        Returns:
            program: new Program instance
        """

        title = serializer.data.get("title")
        existing_program = (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )

        if existing_program is not None:
            program = existing_program
            program.arguments = serializer.data.get("arguments")
            program.entrypoint = serializer.data.get("entrypoint")
            program.dependencies = serializer.data.get("dependencies", "[]")
            program.env_vars = serializer.data.get("env_vars", "{}")
            logger.debug("Program [%s] will be updated by [%s]", title, author)
        else:
            program = Program(**serializer.data)
            logger.debug("Program [%s] will be created by [%s]", title, author)
        program.artifact = artifact
        program.author = author

        # It would be nice if we could unify all the saves logic in one unique entry-point
        try:
            program.save()
        except (Exception) as save_program_exception:
            logger.error(
                "Exception was caught saving the program [%s] by [%s] \n"
                "Error trace: %s",
                title,
                author,
                save_program_exception,
            )
            raise InternalServerErrorException(
                "Unexpected error saving the program"
            ) from save_program_exception

        logger.debug("Program [%s] saved", title)

        return program

    @staticmethod
    def find_one_by_title(title, author) -> Program:
        """
        It returns the last created Program by title from an author

        Args:
            title: program title
            author: user tipically got it from request

        Returns:
            program: Program instance found
        """

        logger.debug("Filtering Program by title[%s] and author [%s]", title, author)
        program = (
            Program.objects.filter(title=title, author=author)
            .order_by("-created")
            .first()
        )

        if program is None:
            logger.error("Program [%s] by author [%s] not found", title, author)
            raise ResourceNotFoundException("Program [{title}] was not found")

        return program


class JobConfigService:
    """
    JobConfig service allocate the logic related with job configuration
    """

    @staticmethod
    def save_with_serializer(serializer) -> JobConfig:
        """
        It returns a new JobConfig from its serializer

        Args:
            serializer: JobConfig serializer from the model

        Returns:
            JobConfig: new JobConfig instance
        """

        # It would be nice if we could unify all the saves logic in one unique entry-point
        try:
            jobconfig = serializer.save()
        except (Exception) as save_job_config_exception:
            logger.error(
                "Exception was caught saving a JobConfig. \n Error trace: %s",
                save_job_config_exception,
            )
            raise InternalServerErrorException(
                "Unexpected error saving the configuration of the job"
            ) from save_job_config_exception

        logger.debug("JobConfig [%s] saved", jobconfig.id)

        return jobconfig


class JobService:
    """
    Job service allocate the logic related with a job
    """

    @staticmethod
    def save(
        program: Program,
        arguments,
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
        print("!!!!")
        print(job.id)
        env = encrypt_env_vars(build_env_variables(token, job, json.dumps(arguments)))
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
