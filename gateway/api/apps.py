"""Applications."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def on_migrations_applied(sender, **kwargs):  # pylint: disable=unused-argument
    """
    This method will run tasks to populate the DB after the migration
    """
    # This import may be here for the correct initialization of the App
    from api.tasks import (  # pylint: disable=import-outside-toplevel
        programs,
        providers,
    )

    providers.assign_admin_groups()
    programs.assign_run_permission()


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        post_migrate.connect(on_migrations_applied, sender=self)
