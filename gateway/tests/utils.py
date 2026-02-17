"""Utilities for tests."""

from typing import Union, Literal

from django.contrib.auth.models import User, Group  # pylint: disable=imported-auth-user
from rest_framework.test import APIClient

from core.models import Job, JobConfig, Program, Provider

# literal for job status
JobStatusType = Literal[
    Job.PENDING, Job.RUNNING, Job.STOPPED, Job.SUCCEEDED, Job.FAILED, Job.QUEUED
]


class TestUtils:
    """Utility class to provide helper methods for gateway testing."""

    @staticmethod
    def _get_user_and_username(author: Union[User, str]) -> tuple[User, str]:
        """Helper to normalize author input into (User object, username string)."""
        if isinstance(author, User):
            return author, author.username

        # If it's a string, get or create the user
        user, _ = User.objects.get_or_create(username=author)
        return user, author

    @staticmethod
    def _get_or_create_provider(provider_admin: str) -> Provider:
        """Helper to setup a provider and its admin group/user safely."""
        provider, _ = Provider.objects.get_or_create(
            name=provider_admin
        )  # provider name is unique
        # Setup Groups and Admin User if needed
        admin_group, _ = Group.objects.get_or_create(name=provider_admin)
        admin_user, _ = User.objects.get_or_create(username=provider_admin)

        if not admin_user.groups.filter(id=admin_group.id).exists():
            admin_user.groups.add(admin_group)

        # Associate group with provider
        if not provider.admin_groups.filter(id=admin_group.id).exists():
            provider.admin_groups.add(admin_group)

        return provider

    @staticmethod
    def create_program(
        author: Union[User, str] = "default_user",
        provider_admin: str = None,
        program_title: str = None,
        **kwargs,
    ) -> Program:
        """
        Creates a Program instance along with its dependencies (User, Provider).
        Args:
            author: The author or username for the Job (and Program).
            provider_admin: Optional username for the provider admin.
            program_title: Optional title. Defaults to author-provider format.
            **kwargs: Additional fields to set on the Program model
        """

        author_obj, author_username = TestUtils._get_user_and_username(author)
        provider = None

        if provider_admin:
            provider = TestUtils._get_or_create_provider(provider_admin)

        if not program_title:
            program_title = f"{author_username}-{provider_admin or 'custom'}"

        program = Program.objects.create(
            title=program_title, author=author_obj, provider=provider, **kwargs
        )
        program.save()
        return program

    @staticmethod
    def create_job_config(
        workers: int = None,
        min_workers: int = 1,
        max_workers: int = 5,
        auto_scaling: bool = True,
        **kwargs,
    ) -> JobConfig:
        """create a JobConfig instance, save it and return it."""
        job_config = JobConfig.objects.create(
            workers=workers,
            min_workers=min_workers,
            max_workers=max_workers,
            auto_scaling=auto_scaling,
            **kwargs,
        )
        job_config.save()
        return job_config

    @staticmethod
    def create_job(  # pylint: disable=too-many-positional-arguments
        author: Union[User, str] = "default_user",
        status: JobStatusType = Job.PENDING,
        config: Union[JobConfig, dict[str, str]] = None,
        provider: str = None,
        program: Program = None,
        title: str = None,
        **kwargs,
    ) -> Job:
        """
        Creates a Job instance along with its dependencies (User, Provider, Program), save it and
        return it.
        Args:
            author: The author or username for the Job (and Program).
            status: Job status. Defaults to Job.PENDING.
            config: Optional JobConfig instance or a dict to create a JobConfig instance.
            provider: Optional admin for the linked Program.
            program: Optional Program instance.
            title: Optional title for the linked Program.
            **kwargs: Fields for the Job.
                     Use the key 'program_fields' (dict) to pass kwargs to the Program.
        """
        author_obj, _ = TestUtils._get_user_and_username(author)
        program_kwargs = kwargs.pop("program_fields", {})  # .pop() removes the key
        if not isinstance(program, Program):
            program = TestUtils.create_program(
                author=author,
                provider_admin=provider,
                program_title=title,
                **program_kwargs,
            )

        if isinstance(config, dict):
            if config.get("id", None):
                # making sure that if id is provided, we will not create an entry with this id.
                config = JobConfig.objects.get(**config)
            else:
                config = JobConfig.objects.create(**config)

        job = Job.objects.create(
            author=author_obj, program=program, status=status, config=config, **kwargs
        )
        job.save()
        return job

    @staticmethod
    def authorize_client(username: str, client: APIClient) -> User:
        """
        Helper to authenticate a DRF test client.
        """
        user, _ = TestUtils._get_user_and_username(author=username)
        client.force_authenticate(user=user)
        return user
