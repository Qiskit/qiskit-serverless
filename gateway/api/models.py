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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    title = models.CharField(max_length=255, db_index=True)
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

    instances = models.ManyToManyField(Group)
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

    TERMINAL_STATES = [SUCCEEDED, FAILED, STOPPED]
    RUNNING_STATES = [RUNNING, PENDING]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True, editable=False)
    updated = models.DateTimeField(auto_now=True, null=True)

    program = models.ForeignKey(to=Program, on_delete=models.SET_NULL, null=True)
    arguments = models.TextField(null=False, blank=True, default="{}")
    env_vars = models.TextField(null=False, blank=True, default="{}")
    result = models.TextField(null=True, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        max_length=10,
        choices=JOB_STATUSES,
        default=QUEUED,
    )
    compute_resource = models.ForeignKey(
        ComputeResource, on_delete=models.SET_NULL, null=True, blank=True
    )
    ray_job_id = models.CharField(max_length=255, null=True, blank=True)
    logs = models.TextField(default="No logs yet.")

    version = IntegerVersionField()

    config = models.ForeignKey(
        to=JobConfig,
        on_delete=models.CASCADE,
        default=None,
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"<Job {self.id} | {self.status}>"

    def in_terminal_state(self):
        """Returns true if job is in terminal state."""
        return self.status in self.TERMINAL_STATES


class RuntimeJob(models.Model):
    """Runtime Job model."""

    job = models.ForeignKey(
        to=Job,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
    )
    runtime_job = models.CharField(
        primary_key=True, max_length=100, blank=False, null=False
    )
    runtime_session = models.CharField(
        max_length=100, blank=True, null=True, default=None
    )
