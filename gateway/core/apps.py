"""Django app configuration for the core module."""

import importlib
import inspect

from django.apps import AppConfig
from django.core.checks import Error, Tags, register

from django.db import models as django_models


class CoreConfig(AppConfig):
    """Configuration class for the core Django application."""

    default_auto_field = "django.db.models.BigAutoField"

    name = "core"

    def ready(self):
        """Register system checks."""
        register(Tags.models)(check_model_labels)


def check_model_labels(app_configs, **kwargs):
    """
    This ensures all models have the same "api_" prefix in the table name and the
    migrations are located in the api app.
    """
    _ = app_configs
    errors = []
    core_models_module = importlib.import_module("core.models")

    for _, obj in inspect.getmembers(core_models_module, inspect.isclass):
        if (
            not issubclass(obj, django_models.Model)
            or obj._meta.abstract
            or obj._meta.app_label == "auth"  # ignore auth.Group and others
        ):
            continue

        if obj._meta.app_label != "api":
            errors.append(
                Error(
                    f"Wrong app_label '{obj._meta.app_label}'. Add this code:\n"
                    f"    class Meta:\n"
                    f'        app_label = "api"',
                    obj=obj,
                )
            )

    return errors
