"""
Django Rest framework models for api application:
    - QuantumFunction
"""

import uuid
from django.core.validators import FileExtensionValidator
from django.db import models
from django_prometheus.models import ExportModelOperationsMixin


def empty_list():
    """
    Returns an empty list.
    """
    return []


def empty_dict():
    """
    Returns an empty dict.
    """
    return {}


class QuantumFunction(ExportModelOperationsMixin("quantumfunction"), models.Model):
    """
    QuantumFunction database model.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    # author = TODO: relationship with user, pending review integration with keycloack
    title = models.CharField(max_length=255, blank=False, null=False)
    description = models.TextField(blank=True, default="")
    entrypoint = models.CharField(max_length=255, blank=False, null=False)
    working_dir = models.CharField(
        max_length=255, blank=False, null=False, default="./"
    )
    version = models.CharField(max_length=100, blank=False, null=False, default="0.0.0")
    dependencies = models.JSONField(null=True, default=empty_list)
    env_vars = models.JSONField(null=True, default=empty_dict)
    arguments = models.JSONField(null=True, default=empty_dict)
    tags = models.JSONField(null=True, default=empty_list)
    public = models.BooleanField(default=True)
    artifact = models.FileField(
        upload_to="artifacts_%Y_%m_%d",
        null=False,
        blank=False,
        validators=[FileExtensionValidator(allowed_extensions=["tar"])],
    )
