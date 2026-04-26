"""Utilities for tests."""

from typing import Union, Literal, Iterable, Tuple

from django.contrib.auth.models import (
    User,
    Group,
    Permission,
)  # pylint: disable=imported-auth-user
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from core.models import Job, JobConfig, JobEvent, Program, Provider
from core.model_managers.job_events import JobEventOrigin, JobEventContext, JobEventType

# literal for job status
JobStatusType = Literal[Job.PENDING, Job.RUNNING, Job.STOPPED, Job.SUCCEEDED, Job.FAILED, Job.QUEUED]
JobSubStatusType = Literal[
    Job.MAPPING, Job.OPTIMIZING_HARDWARE, Job.WAITING_QPU, Job.EXECUTING_QPU, Job.POST_PROCESSING
]


class TestUtils:
    """Utility class to provide helper methods for gateway testing."""

    @staticmethod
    def get_user_and_username(
        author: Union[User, str], is_active: bool = True, is_staff: bool = False
    ) -> tuple[User, str]:
        """Helper to normalize author input into (User object, username string)."""
        if isinstance(author, User):
            return author, author.username

        # If it's a string, get or create the user
        user, _ = User.objects.get_or_create(username=author, defaults={"is_staff": is_staff, "is_active": is_active})
        return user, author

    @staticmethod
    def add_admin_group_to_provider(admin_group: Group, provider: User) -> None:
        """Add admin group to provider. If admin_group does not exist, create it."""
        if isinstance(admin_group, str):
            admin_group = TestUtils.get_or_create_group(group=admin_group)
        # Associate group with provider
        if not provider.admin_groups.filter(id=admin_group.id).exists():
            provider.admin_groups.add(admin_group)

    @staticmethod
    def get_or_create_provider(provider: Union[Provider, str], admin_group: Union[Group, str] = None) -> Provider:
        """
        Setup a provider and its admin group/user safely.
        Args:
            provider: Name for the provider.
            admin_group: Optional admin group name for the provider.
        Returns:
            Provider object
        """
        if isinstance(provider, Provider):
            return provider
        provider, _ = Provider.objects.get_or_create(name=provider)  # provider name is unique
        # Setup Admin Groups if needed
        if admin_group:
            TestUtils.add_admin_group_to_provider(admin_group, provider)
        return provider

    @staticmethod
    def _humanize_permission_name(codename: str, model: str) -> str:
        """
        Best-effort human-readable name for a permission when we create it ad hoc in tests.
        Example: ('run_program', 'program') -> 'Can run program on program'
        """
        codename_pretty = codename.replace("_", " ").strip()
        model_pretty = model.replace("_", " ").strip().title()
        # Django default style is like "Can add program", "Can change program".
        # We'll keep something readable but not overthink it for tests:
        return f"Can {codename_pretty.title()} (Model: {model_pretty})"

    @staticmethod
    def resolve_permission(triple: Tuple[str, str, str]) -> Permission:
        """
        Given (codename, app_label, model), return a Permission.
        Creates the Permission if it doesn't exist (useful for tests).
        """
        codename, app_label, model = triple
        # use ContentType to support all models.
        ct, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
        perm, _ = Permission.objects.get_or_create(
            content_type=ct,
            codename=codename,
            defaults={"name": TestUtils._humanize_permission_name(codename, model)},
        )
        return perm

    @staticmethod
    def get_or_create_group(
        group: Union[Group, str],
        permissions: Iterable[Union[Permission, Tuple[str, str, str]]] = None,
        *,
        replace_permissions: bool = False,
    ) -> Group:
        """
        Create or fetch a Group and attach the given permissions.

        Args:
            group: Group instance or group name.
            permissions: Iterable of either Permission instances OR
                         (codename, app_label, model) triples.
            replace_permissions: If True, the group's permissions are replaced
                                 with exactly the provided set. If False (default),
                                 the provided perms are added on top of existing ones.

        Returns:
            Group
        """

        if isinstance(group, str):
            group, _ = Group.objects.get_or_create(name=group)

        if permissions:
            resolved_perms = []
            for p in permissions:
                if isinstance(p, Permission):
                    resolved_perms.append(p)
                else:
                    # Expecting a (codename, app_label, model) triple
                    if not (isinstance(p, (list, tuple)) and len(p) == 3):
                        raise ValueError(
                            "Each permission must be either a Permission instance "
                            "or a (codename, app_label, model) triple."
                        )
                    resolved_perms.append(TestUtils.resolve_permission(tuple(p)))  # type: ignore

            if replace_permissions:
                group.permissions.set(resolved_perms)
            else:
                group.permissions.add(*resolved_perms)

        return group

    @staticmethod
    def create_program(
        program_title: str,
        author: Union[User, str] = "default_user",
        provider: Union[Provider, str] = None,
        instances: list[Union[Group, str]] = None,
        trial_instances: list[Union[Group, str]] = None,
        **kwargs,
    ) -> Program:
        """
        Creates a Program instance along with its dependencies (User, Provider).
        Args:
            program_title: Optional title. Defaults to author-provider format.
            author: The author or username for the Job (and Program).
            provider: Optional provider or provider name for this program.
            instances: List of group names to add as instances.
            trial_instances: List of group names to add as trial_instances.
            **kwargs: Additional fields to set on the Program model
        """

        author_obj, _ = TestUtils.get_user_and_username(author)

        if not instances:
            instances = []
        if not trial_instances:
            trial_instances = []

        if provider:
            provider = TestUtils.get_or_create_provider(provider)
            if Program.objects.filter(title=program_title, author=author_obj, provider=provider).exists():
                program = Program.objects.get(title=program_title, author=author_obj, provider=provider)
            else:
                program = Program.objects.create(title=program_title, author=author_obj, provider=provider, **kwargs)
        else:
            if Program.objects.filter(title=program_title, author=author_obj, provider=None).exists():
                program = Program.objects.get(title=program_title, author=author_obj)
            else:
                program = Program.objects.create(title=program_title, author=author_obj, **kwargs)

        if instances or trial_instances:
            TestUtils.add_instance_to_program(program, instances=instances, trial_instances=trial_instances)

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
        return job_config

    @staticmethod
    def create_job_event(
        job: Job,
        event_type: JobEventType = JobEventType.STATUS_CHANGE,
        origin: JobEventOrigin = JobEventOrigin.API,
        context: JobEventContext = JobEventContext.RUN_PROGRAM,
        data: dict = None,
    ) -> JobEvent:
        """Create a JobEvent and return it."""
        if not data:
            data = {}
        job_event = JobEvent.objects.create(job=job, event_type=event_type, origin=origin, context=context, data=data)
        job_event.save()
        return job_event

    @staticmethod
    def create_job(  # pylint: disable=too-many-positional-arguments
        author: Union[User, str],
        program: Union[Program, str],
        status: JobStatusType = Job.PENDING,
        config: Union[JobConfig, dict[str, str]] = None,
        **kwargs,
    ) -> Job:
        """
        Creates a Job instance.
        Args:
            author: The author or username for the Job.
            program: The job's program. If program is a string, create a program with this title.
            status: Job status. Defaults to Job.PENDING.
            config: Optional JobConfig instance or a dict to create a JobConfig instance.
            **kwargs: Fields for the Job (like result and logs).
        """
        author_obj, _ = TestUtils.get_user_and_username(author=author)
        if isinstance(config, dict):
            if config.get("id", None):
                # making sure that if id is provided, we will not create an entry with this id.
                config = JobConfig.objects.get(**config)
            else:
                config = JobConfig.objects.create(**config)

        if isinstance(program, str):
            program = TestUtils.create_program(author=author, program_title=program)

        job = Job.objects.create(author=author_obj, program=program, status=status, **kwargs)

        # Creating associate JobEvent for creation of job (status will be pending)
        TestUtils.create_job_event(job)

        if config:
            TestUtils.add_config_to_job(job, config)

        # Adding the status change to the JobEvent table.
        if status != Job.PENDING:
            job_event = JobEvent.objects.add_status_event(
                job_id=job.id, origin=JobEventOrigin.API, context=JobEventContext.RUN_PROGRAM, status=status
            )
            job_event.save()

        return job

    @staticmethod
    def add_config_to_job(job: Job, config: Union[JobConfig, dict[str, str]]) -> Job:
        """Add JobConfig to Job instance."""

        if isinstance(config, dict):
            if config.get("id", None):
                # making sure that if id is provided, we will not create an entry with this id.
                config = JobConfig.objects.get(**config)
            else:
                config = JobConfig.objects.create(**config)
        job.config = config
        job.save(update_fields=["config"])

    @staticmethod
    def add_instance_to_program(
        program: Program,
        instances: list[Union[Group, str]] = None,
        trial_instances: list[Union[Group, str]] = None,
    ):
        """
        Adds instances to a Program (making it have a group access). Creates the group if it doesn't exist.
        """
        # Add instances (groups) if provided
        if instances is not None:
            for group in instances:
                if isinstance(group, str):
                    group = TestUtils.get_or_create_group(group=group)
                program.instances.add(group)

        # Add trial_instances if provided
        if trial_instances is not None:
            for group in trial_instances:
                if isinstance(group, str):
                    group = TestUtils.get_or_create_group(group=group)
                program.trial_instances.add(group)

    @staticmethod
    def add_user_to_group(
        user: Union[User, str],
        group: Union[Group, str],
        permissions: Iterable[Union[Permission, Tuple[str, str, str]]] = None,
    ) -> User:
        """
        Add a user to a group. Creates the group if it doesn't exist.
        Args:
            user: User object or username string
            group: The group or the name of the group to add the user to.
        Returns:
            User object
        """
        user_obj, _ = TestUtils.get_user_and_username(author=user)
        if isinstance(group, str):
            group = TestUtils.get_or_create_group(group=group, permissions=permissions)
        if not user_obj.groups.filter(id=group.id).exists():
            user_obj.groups.add(group)
        return user_obj

    @staticmethod
    def authorize_client(username: str, client: APIClient, is_active: bool = True, is_staff: bool = False) -> User:
        """
        Helper to authenticate a DRF test client.
        """
        user, _ = TestUtils.get_user_and_username(author=username, is_active=is_active, is_staff=is_staff)
        client.force_authenticate(user=user)
        return user
