import uuid
from django.db import models


def empty_list():
    return []


def empty_dict():
    return {}


class NestedProgram(models.Model):
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
    artifact = models.FileField(upload_to="artifacts_%Y_%m_%d", null=False, blank=False)
