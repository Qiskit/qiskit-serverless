"""Models."""
import uuid

from concurrency.fields import IntegerVersionField

from django.core.validators import FileExtensionValidator
from django.db import models
from django.conf import settings
from django_prometheus.models import ExportModelOperationsMixin


def get_upload_path(instance, filename):
    """Returns save path for artifacts."""
    return f"{instance.author.username}/{instance.id}/{filename}"


class Program(ExportModelOperationsMixin("program"), models.Model):
    """Program model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)

    title = models.CharField(max_length=255)
    entrypoint = models.CharField(max_length=255)
    artifact = models.FileField(
        upload_to=get_upload_path,
        null=False,
        blank=False,
        validators=[FileExtensionValidator(allowed_extensions=["tar"])],
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    arguments = models.TextField(null=False, blank=True, default="{}")
    env_vars = models.TextField(null=False, blank=True, default="{}")
    dependencies = models.TextField(null=False, blank=True, default="[]")

    def __str__(self):
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
    created = models.DateTimeField(auto_now_add=True)
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
        default=PENDING,
    )
    compute_resource = models.ForeignKey(
        ComputeResource, on_delete=models.SET_NULL, null=True, blank=True
    )
    ray_job_id = models.CharField(max_length=255, null=True, blank=True)
    logs = models.TextField(default="Here goes nothing.")
    version = IntegerVersionField()

    def __str__(self):
        return f"<Job {self.pk} | {self.status}>"

    def in_terminal_state(self):
        """Returns true if job is in terminal state."""
        return self.status in self.TERMINAL_STATES
