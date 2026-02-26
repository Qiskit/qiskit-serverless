"""Models."""

import logging
import uuid

from concurrency.fields import IntegerVersionField
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.cache import cache
from django.core.validators import FileExtensionValidator
from django.db import models
from django_prometheus.models import ExportModelOperationsMixin

from core.config_key import ConfigKey
from core.model_managers.job_events import JobEventQuerySet

logger = logging.getLogger("gateway")

VIEW_PROGRAM_PERMISSION = "view_program"
RUN_PROGRAM_PERMISSION = "run_program"


def get_upload_path(instance, filename):
    """Returns save path for artifacts."""
    return f"{instance.author.username}/{instance.id}/{filename}"


DEFAULT_PROGRAM_ENTRYPOINT = "main.py"


class JobConfig(models.Model):
    """Job Configuration model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    auto_scaling = models.BooleanField(default=False, null=True)
    workers = models.IntegerField(
        null=True,
    )
    min_workers = models.IntegerField(
        null=True,
    )
    max_workers = models.IntegerField(
        null=True,
    )

    class Meta:
        app_label = "api"

    def __str__(self):
        return f"{self.id}"


class Provider(models.Model):
    """Provider model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, null=True)

    name = models.CharField(max_length=255, db_index=True, unique=True)
    readable_name = models.CharField(max_length=255, null=True, blank=True, default=None)
    url = models.TextField(null=True, blank=True, default=None)
    icon_url = models.TextField(null=True, blank=True, default=None)
    registry = models.CharField(max_length=255, null=True, blank=True, default=None)
    admin_groups = models.ManyToManyField(Group)

    class Meta:
        app_label = "api"

    def __str__(self):
        return f"{self.name}"


class Program(ExportModelOperationsMixin("program"), models.Model):
    """Program model."""

    GENERIC = "GENERIC"
    APPLICATION = "APPLICATION"
    CIRCUIT = "CIRCUIT"
    PROGRAM_TYPES = [
        (GENERIC, "Generic"),
        (APPLICATION, "Application"),
        (CIRCUIT, "Circuit"),
    ]

    DEFAULT_DISABLED_MESSAGE = "IBM has temporarily disabled access to this function"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    title = models.CharField(max_length=255, db_index=True)
    readable_title = models.CharField(max_length=255, null=True, blank=True, default=None)

    disabled = models.BooleanField(default=False, null=False)
    disabled_message = models.TextField(default=DEFAULT_DISABLED_MESSAGE, null=True, blank=True)
    type = models.CharField(
        max_length=20,
        choices=PROGRAM_TYPES,
        default=GENERIC,
    )
    description = models.TextField(null=True, blank=True)
    documentation_url = models.TextField(null=True, blank=True, default=None)
    additional_info = models.TextField(null=True, blank=True, default="{}")

    entrypoint = models.CharField(max_length=255, default=DEFAULT_PROGRAM_ENTRYPOINT)
    artifact = models.FileField(
        upload_to=get_upload_path,
        null=True,
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["tar"])],
    )
    image = models.CharField(max_length=511, null=True, blank=True)
    env_vars = models.TextField(null=False, blank=True, default="{}")
    dependencies = models.TextField(null=False, blank=True, default="[]")

    instances = models.ManyToManyField(Group, blank=True, related_name="program_instances")
    trial_instances = models.ManyToManyField(Group, blank=True, related_name="program_trial_instances")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    provider = models.ForeignKey(
        to=Provider,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
    )

    class Meta:
        app_label = "api"
        permissions = ((RUN_PROGRAM_PERMISSION, "Can run function"),)

    def __str__(self):
        if self.provider:
            return f"{self.provider.name}/{self.title}"
        return f"{self.title}"


class ProgramHistory(models.Model):
    """
    Program History model.
    Every record in this table is an action to add or remove an instance from a program.
    """

    ADD = "ADD"
    REMOVE = "REMOVE"
    ACTIONS = [
        (ADD, "Add"),
        (REMOVE, "Remove"),
    ]

    PROGRAM_FIELD_INSTANCES = "instances"
    PROGRAM_FIELD_TRIAL_INSTANCES = "trial_instances"
    FIELD_NAMES = [
        (PROGRAM_FIELD_INSTANCES, PROGRAM_FIELD_INSTANCES),
        (PROGRAM_FIELD_TRIAL_INSTANCES, PROGRAM_FIELD_TRIAL_INSTANCES),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    action = models.CharField(max_length=255, choices=ACTIONS)
    field_name = models.CharField(max_length=255, choices=FIELD_NAMES)
    entity = models.CharField(max_length=255)
    entity_id = models.CharField(max_length=255)
    description = models.CharField(max_length=255, null=True)
    changed = models.DateTimeField(auto_now_add=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        app_label = "api"


class ComputeResource(models.Model):
    """Compute resource model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)

    title = models.CharField(max_length=100, blank=False, null=False)
    host = models.CharField(max_length=100, blank=False, null=False)

    active = models.BooleanField(default=True, null=True)

    owner = models.ForeignKey(
        to=settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )

    gpu = models.BooleanField(default=False, null=False)

    class Meta:
        app_label = "api"

    def __str__(self):
        return self.title


class Job(models.Model):
    """Job model."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    QUEUED = "QUEUED"
    JOB_STATUSES = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (STOPPED, "Stopped"),
        (SUCCEEDED, "Succeeded"),
        (QUEUED, "Queued"),
        (FAILED, "Failed"),
    ]

    # RUNNING statuses
    MAPPING = "MAPPING"
    OPTIMIZING_HARDWARE = "OPTIMIZING_HARDWARE"
    WAITING_QPU = "WAITING_QPU"
    EXECUTING_QPU = "EXECUTING_QPU"
    POST_PROCESSING = "POST_PROCESSING"

    TERMINAL_STATUSES = [SUCCEEDED, FAILED, STOPPED]
    RUNNING_STATUSES = [RUNNING, PENDING]
    ACTIVE_STATUSES = [QUEUED, PENDING, RUNNING]

    RUNNING_SUB_STATUSES = [
        MAPPING,
        OPTIMIZING_HARDWARE,
        WAITING_QPU,
        EXECUTING_QPU,
        POST_PROCESSING,
    ]

    SUB_STATUSES = [
        (MAPPING, "Mapping"),
        (OPTIMIZING_HARDWARE, "Optimizing for hardware"),
        (WAITING_QPU, "Waiting for QPU"),
        (EXECUTING_QPU, "Executing in QPU"),
        (POST_PROCESSING, "Post-processing"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, null=True)

    arguments = models.TextField(null=False, blank=True, default="{}")
    env_vars = models.TextField(null=False, blank=True, default="{}")
    gpu = models.BooleanField(default=False, null=False)
    logs = models.TextField(default="No logs yet.")
    ray_job_id = models.CharField(max_length=255, null=True, blank=True)
    result = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=10,
        choices=JOB_STATUSES,
        default=QUEUED,
    )
    sub_status = models.CharField(max_length=255, choices=SUB_STATUSES, default=None, null=True, blank=True)
    trial = models.BooleanField(default=False, null=False)
    version = IntegerVersionField()

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    compute_resource = models.ForeignKey(ComputeResource, on_delete=models.SET_NULL, null=True, blank=True)
    config = models.ForeignKey(
        to=JobConfig,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )
    program = models.ForeignKey(to=Program, on_delete=models.SET_NULL, null=True)

    class Meta:
        app_label = "api"

    def __str__(self):
        return f"<Job {self.id} | {self.status}>"

    def in_terminal_state(self):
        """Returns true if job is in terminal state."""
        return self.status in self.TERMINAL_STATUSES


class RuntimeJob(models.Model):
    """Runtime Job model."""

    job = models.ForeignKey(
        to=Job,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
        related_name="runtime_jobs",
    )
    runtime_job = models.CharField(primary_key=True, max_length=100, blank=False, null=False)
    runtime_session = models.CharField(max_length=100, blank=True, null=True, default=None)

    class Meta:
        app_label = "api"


class JobEvent(models.Model):
    """Events history for jobs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        to=Job,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
        related_name="job_events",
    )
    event_type = models.CharField(max_length=100, blank=False, null=False)
    origin = models.CharField(max_length=100, blank=False, null=False)
    context = models.CharField(max_length=100, blank=False, null=False)
    created = models.DateTimeField(auto_now_add=True, null=True)
    data = models.JSONField(default=dict, blank=False, null=False)

    objects = JobEventQuerySet.as_manager()

    class Meta:
        app_label = "api"
        ordering = ("-created",)


class GroupMetadata(models.Model):
    """
    This model will store metadata from different resources for Group
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    # This field will store the account_id from IBM Cloud.
    account = models.CharField(max_length=255, blank=True, null=True, default=None)

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="metadata")

    class Meta:
        app_label = "api"

    def __str__(self):
        return f"{self.id}"


class Config(models.Model):
    """Dynamic configuration stored in database with caching."""

    name = models.CharField(max_length=255, unique=True, db_index=True)
    value = models.TextField()
    description = models.TextField(blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        app_label = "api"
        verbose_name = "Configuration"
        verbose_name_plural = "Config values"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} = {self.value}"

    @classmethod
    def _get_cache_key(cls, key: ConfigKey) -> str:
        return f"dynamic_config:{key.value}"

    @classmethod
    def register_all(cls):
        """Insert in the db the default values from the configuration keys defined in the ConfigKey enum."""
        for value in (k.value for k in ConfigKey):
            if value not in settings.DYNAMIC_CONFIG_DEFAULTS:
                raise KeyError(f"ConfigKey '{value}' not found in DYNAMIC_CONFIG_DEFAULTS. Add it to setting.py")

            config_entry = settings.DYNAMIC_CONFIG_DEFAULTS[value]
            if "default" not in config_entry or "description" not in config_entry:
                raise KeyError(f"Error in settings.DYNAMIC_CONFIG_DEFAULTS['{value}'] Missing default/description.")

            default = config_entry["default"]
            description = config_entry["description"]
            _, created = cls.objects.get_or_create(
                name=value,
                defaults={"value": default, "description": description},
            )
            if created:
                logger.info("Registered new Config: %s = %s", value, default)

    @classmethod
    def set(cls, key: ConfigKey, value: str):
        """Changes a configuration value in DB and cache."""
        cls.objects.filter(name=key.value).update(value=value)
        cache.set(cls._get_cache_key(key), value, settings.DYNAMIC_CONFIG_CACHE_TTL)

    @classmethod
    def get(cls, key: ConfigKey) -> str:
        """Get configuration value with caching. Raises KeyError if key was not registered."""
        cache_key = cls._get_cache_key(key)
        cached_value = cache.get(cache_key)

        if cached_value is not None:
            return cached_value

        try:
            config = cls.objects.get(name=key.value)
            cache.set(cache_key, config.value, settings.DYNAMIC_CONFIG_CACHE_TTL)
            return config.value
        except cls.DoesNotExist as exc:
            raise KeyError(f"Config '{key.value}' not found in db. Call register_all() before") from exc

    @classmethod
    def get_bool(cls, key: ConfigKey) -> bool:
        """Get configuration value as boolean."""
        value = cls.get(key)
        return value.lower() == "true"
