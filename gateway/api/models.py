"""Models."""

import uuid

from concurrency.fields import IntegerVersionField
from django.contrib.auth.models import Group
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django_prometheus.models import ExportModelOperationsMixin

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

    def __str__(self):
        return f"{self.id}"


class Provider(models.Model):
    """Provider model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, null=True)

    name = models.CharField(max_length=255, db_index=True, unique=True)
    readable_name = models.CharField(
        max_length=255, null=True, blank=True, default=None
    )
    url = models.TextField(null=True, blank=True, default=None)
    icon_url = models.TextField(null=True, blank=True, default=None)
    registry = models.CharField(max_length=255, null=True, blank=True, default=None)
    admin_groups = models.ManyToManyField(Group)

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
    readable_title = models.CharField(
        max_length=255, null=True, blank=True, default=None
    )

    disabled = models.BooleanField(default=False, null=False)
    disabled_message = models.TextField(
        default=DEFAULT_DISABLED_MESSAGE, null=True, blank=True
    )
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

    instances = models.ManyToManyField(
        Group, blank=True, related_name="program_instances"
    )
    trial_instances = models.ManyToManyField(
        Group, blank=True, related_name="program_trial_instances"
    )
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
    sub_status = models.CharField(
        max_length=255, choices=SUB_STATUSES, default=None, null=True, blank=True
    )
    trial = models.BooleanField(default=False, null=False)
    version = IntegerVersionField()

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    compute_resource = models.ForeignKey(
        ComputeResource, on_delete=models.SET_NULL, null=True, blank=True
    )
    config = models.ForeignKey(
        to=JobConfig,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )
    program = models.ForeignKey(to=Program, on_delete=models.SET_NULL, null=True)

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
    runtime_job = models.CharField(
        primary_key=True, max_length=100, blank=False, null=False
    )
    runtime_session = models.CharField(
        max_length=100, blank=True, null=True, default=None
    )


class GroupMetadata(models.Model):
    """
    This model will store metadata from different resources for Group
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    # This field will store the account_id from IBM Cloud.
    account = models.CharField(max_length=255, blank=True, null=True, default=None)

    group = models.OneToOneField(
        Group, on_delete=models.CASCADE, related_name="metadata"
    )

    def __str__(self):
        return f"{self.id}"
