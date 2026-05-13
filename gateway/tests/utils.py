"""Utilities for tests."""

from typing import Union, Literal, Iterable, Tuple

from django.contrib.auth.models import (
    User,
    Group,
    Permission,
)  # pylint: disable=imported-auth-user
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.models import Job, JobConfig, JobEvent, Program, Provider, ComputeResource
from core.model_managers.job_events import JobEventOrigin, JobEventContext, JobEventType

# literal for job status
JobStatusType = Literal[Job.PENDING, Job.RUNNING, Job.STOPPED, Job.SUCCEEDED, Job.FAILED, Job.QUEUED]
JobSubStatusType = Literal[
    Job.MAPPING, Job.OPTIMIZING_HARDWARE, Job.WAITING_QPU, Job.EXECUTING_QPU, Job.POST_PROCESSING
]


class TestUtils:
    # pylint: disable=line-too-long
    """Utility class to provide helper methods for gateway testing.

    This class provides static methods to simplify test setup by creating and managing
    Django models (User, Group, Permission, Provider, Program, Job, JobConfig, JobEvent).
    """
    # pylint: enable=line-too-long

    @staticmethod
    def get_user_and_username(
        author: Union[User, str], is_active: bool = True, is_staff: bool = False
    ) -> tuple[User, str]:
        """Normalize author input into User object and username string.

        Accepts either a User instance or username string and returns a tuple
        containing the User object and username. Creates a new User in the database
        if a string is provided and the user doesn't exist.

        Args:
            author: User instance or username string to normalize. If is str, creates User with username=author
            (if doesn't exist)
            is_active: Whether the created user should be active. Only used when
                creating new users (author is str). Default is True.
            is_staff: Whether the created user should have staff privileges. Only
                used when creating new users (author is str). Default is False.

        Returns:
            Tuple containing the User object and username string.
        """
        if isinstance(author, User):
            return author, author.username

        # If it's a string, get or create the user
        user, _ = User.objects.get_or_create(username=author, defaults={"is_staff": is_staff, "is_active": is_active})
        return user, author

    @staticmethod
    def add_admin_group_to_provider(admin_group: Group, provider: User) -> None:
        """Associate an admin group with a provider.

        Links the specified admin group to the provider's admin_groups. Creates
        the group if a string is provided instead of a Group instance.

        Args:
            admin_group: Group instance or group name string to add as admin.
            provider: Provider instance to associate the admin group with.
        """
        if isinstance(admin_group, str):
            admin_group = TestUtils.get_or_create_group(group=admin_group)
        # Associate group with provider (could need admin_user associate with group to work)
        if not provider.admin_groups.filter(id=admin_group.id).exists():
            provider.admin_groups.add(admin_group)

    @staticmethod
    def get_or_create_provider(provider: Union[Provider, str], admin_group: Union[Group, str] = None) -> Provider:
        """Get or create a Provider instance with optional admin group.

        Retrieves an existing Provider or creates a new one if it doesn't exist.
        Optionally associates an admin group with the provider.

        Args:
            provider: Provider instance or provider name string.
            admin_group: Optional Group instance or group name string to set as
                admin group for the provider.

        Returns:
            Provider instance.
        """
        if isinstance(provider, Provider):
            return provider
        provider, _ = Provider.objects.get_or_create(name=provider)  # provider name is unique
        # Setup Admin Groups if needed
        if admin_group:
            TestUtils.add_admin_group_to_provider(admin_group, provider)
        return provider

    @staticmethod
    def get_or_create_compute_resource(
        title: str,
        host: str = "localhost",
        active: bool = True,
        owner: Union[User, str] = None,
        gpu: bool = False,
    ) -> ComputeResource:
        """Get or create a ComputeResource instance.

        Retrieves an existing ComputeResource by title or creates a new one with
        the specified configuration.

        Args:
            title: Unique title for the compute resource.
            host: Host address for the compute resource. Default is "localhost".
            active: Whether the resource is active and available. Default is True.
            owner: Optional User instance or username string who owns the resource. If is str, creates User with
            username=owner (if doesn't exist)
            gpu: Whether this is a GPU-enabled resource. Default is False.

        Returns:
            ComputeResource instance.
        """
        # Get or create owner if provided
        owner_obj = None
        if owner:
            owner_obj, _ = TestUtils.get_user_and_username(author=owner)

        # Get or create ComputeResource
        compute_resource, _ = ComputeResource.objects.get_or_create(
            title=title,
            defaults={
                "host": host,
                "active": active,
                "owner": owner_obj,
                "gpu": gpu,
            },
        )
        return compute_resource

    @staticmethod
    def _humanize_permission_name(codename: str, model: str) -> str:
        """Generate human-readable permission name for test permissions.

        Creates a descriptive name for permissions created during testing.

        Args:
            codename: Permission codename (e.g., 'run_program').
            model: Model name the permission applies to (e.g., 'program').

        Returns:
            Human-readable permission name string.
        """
        codename_pretty = codename.replace("_", " ").strip()
        model_pretty = model.replace("_", " ").strip().title()
        # Django default style is like "Can add program", "Can change program".
        # We'll keep something readable but not overthink it for tests:
        return f"Can {codename_pretty.title()} (Model: {model_pretty})"

    @staticmethod
    def resolve_permission(triple: Tuple[str, str, str]) -> Permission:
        """Get or create a Permission from codename, app_label, and model.

        Resolves a permission triple into a Permission instance, creating the
        Permission and ContentType if they don't exist.

        Args:
            triple: Tuple of (codename, app_label, model) identifying the permission.

        Returns:
            Permission instance.

        Note:
            Database changes:
            - Creates ContentType for (app_label, model) if doesn't exist
            - Creates Permission with given codename and content_type if doesn't exist
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
        """Get or create a Group and attach permissions.

        Retrieves an existing Group or creates a new one, then attaches the
        specified permissions. Permissions can be provided as Permission instances
        or as (codename, app_label, model) tuples.

        Args:
            group: Group instance or group name string.
            permissions: Optional iterable of Permission instances or
                (codename, app_label, model) tuples to attach to the group.
            replace_permissions: If True, replaces all existing group permissions.
                If False, adds to existing permissions. Default is False.

        Returns:
            Group instance.

        Raises:
            ValueError: If a permission is neither a Permission instance nor a
                valid (codename, app_label, model) tuple.
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
        """Create a Program with dependencies.

        Creates a Program instance along with any required dependencies (User,
        Provider, Groups). Returns existing Program if one with the same title,
        author, and provider already exists.

        Args:
            program_title: Title for the program.
            author: User instance or username string. Default is "default_user".
            provider: Optional Provider instance or provider name string.
            instances: Optional list of Group instances or group name strings
                to add as program instances (full access groups).
            trial_instances: Optional list of Group instances or group name strings
                to add as trial instances (limited access groups).
            **kwargs: Additional fields to set on the Program model.

        Returns:
            Program instance.
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
        """Create a JobConfig instance.

        Creates and saves a new JobConfig with the specified worker configuration.

        Args:
            workers: Fixed number of workers. If None, uses auto_scaling. Default is None.
            min_workers: Minimum workers for auto_scaling. Default is 1.
            max_workers: Maximum workers for auto_scaling. Default is 5.
            auto_scaling: Whether to enable auto_scaling. Default is True.
            **kwargs: Additional fields to set on the JobConfig model.

        Returns:
            JobConfig instance.
        """
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
        """Create a JobEvent for tracking job lifecycle.

        Creates and saves a JobEvent associated with the specified job.

        Args:
            job: Job instance to associate the event with.
            event_type: Type of event. Default is STATUS_CHANGE.
            origin: Origin of the event. Default is API.
            context: Context in which the event occurred. Default is RUN_PROGRAM.
            data: Optional dictionary of additional event data. Default is empty dict.

        Returns:
            JobEvent instance.
        """
        if not data:
            data = {}
        job_event = JobEvent.objects.create(job=job, event_type=event_type, origin=origin, context=context, data=data)
        job_event.save()
        return job_event

    @staticmethod
    def create_job(  # pylint: disable=too-many-positional-arguments
        author: Union[User, str],
        program: Union[Program, str],
        status: JobStatusType = Job.QUEUED,
        config: Union[JobConfig, dict[str, str]] = None,
        **kwargs,
    ) -> Job:
        """Create a Job with full dependency chain.

        Creates a Job instance along with all required dependencies and associated
        JobEvents. Always creates an initial QUEUED JobEvent, and creates an
        additional status change event if the status is not QUEUED.

        Args:
            author: User instance or username string who created the job.
            program: Program instance or program title string to run.
            status: Initial job status. Default is Job.QUEUED.
            config: Optional JobConfig instance or dict of config parameters.
                If dict with 'id' key: fetches existing JobConfig.
                If dict without 'id': creates new JobConfig.
            **kwargs: Additional fields to set on the Job model (e.g., result, logs).

        Returns:
            Job instance.
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

        # Creating associate JobEvent for creation of job (status will be QUEUED)
        TestUtils.create_job_event(job)

        if config:
            TestUtils.add_config_to_job(job, config)

        # Adding the status change to the JobEvent table.
        if status != Job.QUEUED:
            job_event = JobEvent.objects.add_status_event(
                job_id=job.id, origin=JobEventOrigin.API, context=JobEventContext.RUN_PROGRAM, status=status
            )
            job_event.save()

        return job

    @staticmethod
    def add_config_to_job(job: Job, config: Union[JobConfig, dict[str, str]]) -> Job:
        """Associate a JobConfig with a Job.

        Links the specified JobConfig to the job, creating the config if a
        dictionary is provided.

        Args:
            job: Job instance to add configuration to.
            config: JobConfig instance or dict of config parameters.
                If dict with 'id' key: fetches existing JobConfig.
                If dict without 'id': creates new JobConfig.

        Returns:
            Job instance (same as input, for chaining).
        """
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
        """Add instance and trial_instance groups to a Program.

        Associates groups with the program to control access. Instance groups
        have full access, while trial_instance groups have limited access.

        Args:
            program: Program instance to add groups to.
            instances: Optional list of Group instances or group name strings
                to add as full-access instances.
            trial_instances: Optional list of Group instances or group name strings
                to add as limited-access trial instances.
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
    ) -> tuple[User, Group]:
        """Add a user to a group with optional permissions.

        Associates a user with a group, creating both if necessary. Optionally
        adds permissions to the group.

        Args:
            user: User instance or username string to add to the group.
            group: Group instance or group name string to add the user to.
            permissions: Optional iterable of Permission instances or
                (codename, app_label, model) tuples to add to the group.

        Returns:
            Tuple of (User instance, Group instance).
        """
        user_obj, _ = TestUtils.get_user_and_username(author=user)
        if isinstance(group, str):
            group = TestUtils.get_or_create_group(group=group, permissions=permissions)
        if not user_obj.groups.filter(id=group.id).exists():
            user_obj.groups.add(group)
        return user_obj, group

    @staticmethod
    def authorize_client(
        user: Union[str, User], client: APIClient, is_active: bool = True, is_staff: bool = False,
        accessible_functions: FunctionAccessResult=None, token=None,
    ) -> User:
        """Authenticate a DRF test client with a user.

        onfigures the APIClient to make authenticated requests as the specified
        user with a mock authentication token.

        Args:
            user: User instance or username string to authenticate as.
            client: APIClient instance to authenticate.
            is_active: Whether the created user should be active. Only used when
                creating new users (user is str). Default is True.
            is_staff: Whether the created user should have staff privileges. Only
                used when creating new users (user is str). Default is False.
            accessible_functions: User accessible functions to use. If 'None', initialize defaults.
            token: Optional DRF token to authenticate with. If 'None', initialize defaults.,

        Returns:
            User instance that was authenticated.
        """
        from unittest.mock import MagicMock

        from api.domain.authentication.channel import Channel

        user_obj, _ = TestUtils.get_user_and_username(author=user, is_active=is_active, is_staff=is_staff)
        if not token:
            token = MagicMock()
            if isinstance(accessible_functions, FunctionAccessResult):
                token.accessible_functions = accessible_functions
            else:
                token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
            token.channel = Channel.LOCAL
            token.token = b"test-token"
            token.instance = None
            token.account_id = None
        elif isinstance(accessible_functions, FunctionAccessResult):
                token.accessible_functions = accessible_functions
        client.force_authenticate(user=user_obj, token=token)
        return user_obj


def create_function_access_result(
    provider_name,
    function_title,
    permissions,
    business_model=BusinessModel.SUBSIDIZED,
):
    """Create a FunctionAccessResult for testing authorization.

    Creates a FunctionAccessResult with a single function access entry for
    testing function-level authorization.

    Args:
        provider_name: Name of the provider offering the function.
        function_title: Title of the function to grant access to.
        permissions: Permissions to grant for the function.
        business_model: Business model for the function. Default is SUBSIDIZED.

    Returns:
        FunctionAccessResult instance with a single function entry.
    """
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=business_model,
    )
    return FunctionAccessResult(use_legacy_authorization=False, functions=[entry])
