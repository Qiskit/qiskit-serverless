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

    ## Public Methods Summary (With Minimal Input)

    Method                      | Essential Input           | Optional Input                | Creates (minimal)                | Returns
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    get_user_and_username       | author (User/str)         | is_active (bool),             | User (if str)                    | tuple[User, str]
                                |                           | is_staff (bool)               |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    get_or_create_provider      | provider (Provider/str)   | admin_group (Group/str)       | Provider (if str)                | Provider
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    get_or_create_compute_      | title (str)               | host (str), active (bool),    | ComputeResource                  | ComputeResource
    resource                    |                           | owner (User/str), gpu (bool)  |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    get_or_create_group         | group (Group/str)         | permissions (list),           | Group (if str)                   | Group
                                |                           | replace_permissions (bool)    |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    create_program              | program_title (str)       | author (User/str),            | Program, User (if author is str) | Program
                                |                           | provider (Provider/str),      |                                  |
                                |                           | instances (list),             |                                  |
                                |                           | trial_instances (list),       |                                  |
                                |                           | **kwargs                      |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    create_job_config           | -                         | workers (int),                | JobConfig                        | JobConfig
                                |                           | min_workers (int),            |                                  |
                                |                           | max_workers (int),            |                                  |
                                |                           | auto_scaling (bool),          |                                  |
                                |                           | **kwargs                      |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    create_job_event            | job (Job)                 | event_type (JobEventType),    | JobEvent                         | JobEvent
                                |                           | origin (JobEventOrigin),      |                                  |
                                |                           | context (JobEventContext),    |                                  |
                                |                           | data (dict)                   |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    create_job                  | author (User/str),        | status (JobStatusType),       | Job, User (if author is str),    | Job
                                | program (Program/str)     | config (JobConfig/dict),      | JobEvent (initial + status       |
                                |                           | **kwargs                      | change if not QUEUED)            |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    add_config_to_job           | job (Job),                | -                             | JobConfig (if config is dict     | None
                                | config (JobConfig/dict)   |                               | without id)                      |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    add_instance_to_program     | program (Program)         | instances (list),             | -                                | None
                                |                           | trial_instances (list)        |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    add_user_to_group           | user (User/str),          | permissions (list)            | User (if str), Group (if str)    | tuple[User, Group]
                                | group (Group/str)         |                               |                                  |
    ----------------------------|---------------------------|-------------------------------|----------------------------------|--------------------
    authorize_client            | user (User/str),          | is_active (bool),             | User (if user is str and doesn't | User
                                | client (APIClient)        | is_staff (bool)               | exist)                           |


    ## Public Methods Summary (With Optional Input))

    Method                      |Optional Input Creates
    ----------------------------|---------------------------------------------------
    get_user_and_username       |-
                                |
    ----------------------------|---------------------------------------------------
    get_or_create_provider      | Group (if admin_group is str)
    ----------------------------|---------------------------------------------------
    get_or_create_compute_      | User (if owner is str)
    resource                    |
    ----------------------------|---------------------------------------------------
    get_or_create_group         | Permission (if tuple in permissions)
                                |
    ----------------------------|---------------------------------------------------
    create_program              | Provider (if str), Groups (if instances/
                                | trial_instances are str)
                                |
    ----------------------------|---------------------------------------------------
    create_job_config           |-
                                |
    ----------------------------|---------------------------------------------------
    create_job_event            |-
                                |
    ----------------------------|---------------------------------------------------
    create_job                  | Program (if str), JobConfig (if dict), Provider
                                | (if program is str with provider)
                                |
    ----------------------------|---------------------------------------------------
    add_config_to_job           |-
                                |
    ----------------------------|---------------------------------------------------
    add_instance_to_program     | Groups (if str in lists)
                                |
    ----------------------------|---------------------------------------------------
    add_user_to_group           | Permission (if tuple in permissions)
                                |
    ----------------------------|---------------------------------------------------
    authorize_client            |-
                                |


    ## Detailed Method Descriptions

    ### User & Authentication Methods

    **`get_user_and_username(author, is_active=True, is_staff=False)`**
    - Normalizes author input into (User object, username string)
    - If `author` is User: returns (author, author.username)
    - If `author` is str: gets or creates User with username=author

    **`authorize_client(user, client, is_active=True, is_staff=False)`** → User
    - Authenticates a DRF test client with a user
    - If `user` is str: creates User if doesn't exist via `get_user_and_username()`
    - Calls client.force_authenticate(user)

    ### Group & Permission Methods

    **`get_or_create_group(group, permissions=None, replace_permissions=False)`**
    - Creates or fetches a Group and attaches permissions
    - If `group` is str: creates Group with name=group
    - If `permissions` contains Permission instances: adds them directly
    - If `permissions` contains (codename, app_label, model) tuples: resolves to Permission
    - If `replace_permissions=True`: replaces all group permissions
    - If `replace_permissions=False`: adds to existing permissions

    **`resolve_permission(triple)`**
    - Given (codename, app_label, model), returns Permission
    - Creates Permission if doesn't exist
    - Creates ContentType if doesn't exist

    **`add_user_to_group(user, group, permissions=None)`**
    - Adds user to group (creates both if strings)
    - If `user` is str: creates User
    - If `group` is str: creates Group via `get_or_create_group()`
    - If `permissions` provided: adds them to group

    ### Provider Methods

    **`get_or_create_provider(provider, admin_group=None)`** → Provider
    - Creates or fetches Provider
    - If `provider` is str: creates Provider with name=provider
    - If `admin_group` provided (str or Group): associates it with provider via `add_admin_group_to_provider()`

    **`add_admin_group_to_provider(admin_group, provider)`** → None
    - Associates admin group with provider
    - If `admin_group` is str: creates Group via `get_or_create_group()`

    ### ComputeResource Methods

    **`get_or_create_compute_resource(title, host='localhost', active=True, owner=None, gpu=False)`** → ComputeResource
    - Get or create a ComputeResource instance with given title and host
    - If `owner` is str: creates User via `get_user_and_username()`
    - If ComputeResource with title exists, returns existing one

    ### Program Methods

    **`create_program(program_title, author='default_user', provider=None, ...)`**
    - Creates Program with dependencies
    - If `author` is str: creates User
    - If `provider` is str: creates Provider via `get_or_create_provider()`
    - If `instances` contains str: creates Groups via `get_or_create_group()`
    - If `trial_instances` contains str: creates Groups
    - Returns existing Program if (title, author, provider) combination exists

    **`add_instance_to_program(program, instances=None, trial_instances=None)`**
    - Adds instance/trial_instance groups to Program
    - If group names are str: creates Groups via `get_or_create_group()`

    ### Job & JobConfig Methods

    **`create_job_config(workers=None, min_workers=1, max_workers=5, ...)`**
    - Creates JobConfig with specified parameters

    **`create_job_event(job, event_type=STATUS_CHANGE, origin=API, ...)`**
    - Creates JobEvent for a job
    - Defaults: event_type=STATUS_CHANGE, origin=API, context=RUN_PROGRAM

    **`create_job(author, program, status=QUEUED, config=None, **kwargs)`**
    - Creates Job with full dependency chain
    - If `author` is str: creates User
    - If `program` is str: creates Program (which may create User, Provider)
    - If `config` is dict without 'id': creates JobConfig
    - If `config` is dict with 'id': fetches existing JobConfig
    - Always creates initial JobEvent (QUEUED status)
    - If `status != QUEUED`: creates additional JobEvent for status change

    **`add_config_to_job(job, config)`**
    - Associates JobConfig with Job
    - If `config` is dict without 'id': creates JobConfig
    - If `config` is dict with 'id': fetches existing JobConfig

    ## Usage Examples

    ```python
    # Minimal job creation (creates User, Program, Job, 2 JobEvents)
    job = TestUtils.create_job(author="testuser", program="testprogram")

    # Full job with dependencies
    job = TestUtils.create_job(
        author="testuser",
        program="testprogram",
        status=Job.RUNNING,
        config={"workers": 3}
    )

    # Program with provider and access control
    program = TestUtils.create_program(
        program_title="My Program",
        author="testuser",
        provider="ibm",
        instances=["premium_users"]
    )

    # Authenticate test client
    user = TestUtils.authorize_client(user="testuser", client=self.client)
    ```
    """
    # pylint: enable=line-too-long

    @staticmethod
    def get_user_and_username(
        author: Union[User, str], is_active: bool = True, is_staff: bool = False
    ) -> tuple[User, str]:
        """Helper to normalize author input into (User object, username string).

        - **Minimal creates**: User (if author is str)
        - **Optional creates**: None
        - Behavior:
          * If `author` is User: returns (author, author.username)
          * If `author` is str: gets or creates User with username=author
        """
        if isinstance(author, User):
            return author, author.username

        # If it's a string, get or create the user
        user, _ = User.objects.get_or_create(username=author, defaults={"is_staff": is_staff, "is_active": is_active})
        return user, author

    @staticmethod
    def add_admin_group_to_provider(admin_group: Group, provider: User) -> None:
        """Add admin group to provider. If admin_group does not exist, create it.

        - **Minimal creates**: Group (if admin_group is str)
        - Behavior:
          * If `admin_group` is str: creates Group via `get_or_create_group()`
          * Associates group with provider.admin_groups
        """
        if isinstance(admin_group, str):
            admin_group = TestUtils.get_or_create_group(group=admin_group)
        # Associate group with provider (could need admin_user associate with group to work)
        if not provider.admin_groups.filter(id=admin_group.id).exists():
            provider.admin_groups.add(admin_group)

    @staticmethod
    def get_or_create_provider(provider: Union[Provider, str], admin_group: Union[Group, str] = None) -> Provider:
        """Setup a provider and its admin group/user safely.

        - **Minimal creates**: Provider (if str)
        - **Optional creates**: Group (if admin_group is str)
        - Behavior:
          * If `provider` is str: creates Provider with name=provider
          * If `admin_group` provided (str or Group): associates it with provider via `add_admin_group_to_provider()`

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
    def get_or_create_compute_resource(
        title: str,
        host: str = "localhost",
        active: bool = True,
        owner: Union[User, str] = None,
        gpu: bool = False,
    ) -> ComputeResource:
        """Get or create a ComputeResource instance.

        - **Minimal creates**: ComputeResource
        - **Optional creates**: User (if owner is str)
        - Behavior:
          * Creates ComputeResource with given title and host
          * If `owner` is str: creates User via `get_user_and_username()`
          * If ComputeResource with title exists, returns existing one

        Args:
            title: Title for the compute resource
            host: Host address (default: "localhost")
            active: Whether the resource is active (default: True)
            owner: Optional owner User object or username string
            gpu: Whether this is a GPU resource (default: False)

        Returns:
            ComputeResource object
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
        """Best-effort human-readable name for a permission when we create it ad hoc in tests.

        Example: ('run_program', 'program') -> 'Can run program on program'
        """
        codename_pretty = codename.replace("_", " ").strip()
        model_pretty = model.replace("_", " ").strip().title()
        # Django default style is like "Can add program", "Can change program".
        # We'll keep something readable but not overthink it for tests:
        return f"Can {codename_pretty.title()} (Model: {model_pretty})"

    @staticmethod
    def resolve_permission(triple: Tuple[str, str, str]) -> Permission:
        """Given (codename, app_label, model), return a Permission.

        - **Minimal creates**: Permission, ContentType (if don't exist)
        - Behavior:
          * Creates Permission if doesn't exist
          * Creates ContentType if doesn't exist
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
        """Create or fetch a Group and attach the given permissions.

        - **Minimal creates**: Group (if group is str)
        - **Optional creates**: Permission (if tuple in permissions list)
        - Behavior:
          * If `group` is str: creates Group with name=group
          * If `permissions` contains Permission instances: adds them directly
          * If `permissions` contains (codename, app_label, model) tuples: creates Permission via `resolve_permission()`
          * If `replace_permissions=True`: replaces all group permissions
          * If `replace_permissions=False`: adds to existing permissions

        Args:
            group: Group instance or group name.
            permissions: Iterable of either Permission instances OR (codename, app_label, model) triples.
            replace_permissions: If True, replaces group permissions. If False (default), adds to existing.

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
        """Creates a Program instance along with its dependencies (User, Provider).

        - **Minimal creates**: Program, User (if author is str)
        - **Optional creates**: Provider (if str), Groups (if instances/trial_instances contain str)
        - Behavior:
          * If `author` is str: creates User via `get_user_and_username()`
          * If `provider` is str: creates Provider via `get_or_create_provider()`
          * If `instances` contains str: creates Groups via `get_or_create_group()`
          * If `trial_instances` contains str: creates Groups via `get_or_create_group()`
          * Creates Program if (title, author, provider) combination doesn't exist, otherwise fetches existing Program

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
        """Create a JobConfig instance, save it and return it.

        - **Minimal creates**: JobConfig
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
        """Create a JobEvent and return it.

        - **Minimal creates**: JobEvent
        - Defaults: event_type=STATUS_CHANGE, origin=API, context=RUN_PROGRAM
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
        """Creates a Job instance with full dependency chain.

        - **Minimal creates**: Job, User (if author is str), JobEvent (initial + status change if not QUEUED)
        - **Optional creates**: Program (if str), JobConfig (if dict), Provider (if program is str with provider)
        - Behavior:
          * If `author` is str: creates User via `get_user_and_username()`
          * If `program` is str: creates Program via `create_program()` (which may create User, Provider)
          * If `config` is dict without 'id': creates JobConfig
          * If `config` is dict with 'id': fetches existing JobConfig
          * Always creates initial JobEvent (QUEUED status)
          * If `status != QUEUED`: creates additional JobEvent for status change

        Args:
            author: The author or username for the Job.
            program: The job's program. If program is a string, create a program with this title.
            status: Job status. Defaults to Job.QUEUED.
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
        """Add JobConfig to Job instance.

        - **Minimal creates**: JobConfig (if config is dict without id)
        - Behavior:
          * If `config` is dict without 'id': creates JobConfig
          * If `config` is dict with 'id': fetches existing JobConfig
          * Updates job.config and saves
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
        """Adds instances to a Program (making it have group access). Creates the group if it doesn't exist.

        - **Optional creates**: Groups (if str in lists)
        - Behavior:
          * If group names in `instances` are str: creates Groups via `get_or_create_group()`
          * If group names in `trial_instances` are str: creates Groups via `get_or_create_group()`
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
        """Add a user to a group. Creates the group if it doesn't exist.

        - **Minimal creates**: User (if str), Group (if str)
        - **Optional creates**: Permission (if tuple in permissions list)
        - Behavior:
          * If `user` is str: creates User via `get_user_and_username()`
          * If `group` is str: creates Group via `get_or_create_group()`
          * If `permissions` provided: adds them to group (may create Permission objects)

        Args:
            user: User object or username string
            group: The group or the name of the group to add the user to.
        Returns:
            tuple[User, Group]
        """
        user_obj, _ = TestUtils.get_user_and_username(author=user)
        if isinstance(group, str):
            group = TestUtils.get_or_create_group(group=group, permissions=permissions)
        if not user_obj.groups.filter(id=group.id).exists():
            user_obj.groups.add(group)
        return user_obj, group

    @staticmethod
    def authorize_client(
        user: Union[str, User], client: APIClient, is_active: bool = True, is_staff: bool = False
    ) -> User:
        """Helper to authenticate a DRF test client.

        - **Minimal creates**: User (if user is str and doesn't exist)
        - Behavior:
          * If `user` is str: creates User if doesn't exist via `get_user_and_username()`
          * Calls client.force_authenticate(user)
        """
        from unittest.mock import MagicMock

        from api.domain.authentication.channel import Channel

        user_obj, _ = TestUtils.get_user_and_username(author=user, is_active=is_active, is_staff=is_staff)
        token = MagicMock()
        token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
        token.channel = Channel.LOCAL
        token.token = b"test-token"
        token.instance = None
        client.force_authenticate(user=user_obj, token=token)
        return user_obj


def create_function_access_result(
    provider_name,
    function_title,
    permissions,
    business_model=BusinessModel.SUBSIDIZED,
):
    """Return a FunctionAccessResult with a single entry for the given provider/function/permissions."""
    entry = FunctionAccessEntry(
        provider_name=provider_name,
        function_title=function_title,
        permissions=permissions,
        business_model=business_model,
    )
    return FunctionAccessResult(use_legacy_authorization=False, functions=[entry])
