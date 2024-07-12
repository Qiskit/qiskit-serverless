"""Applications."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ApiConfig(AppConfig):
    """ApiConfig."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "api"

    def ready(self):
        def on_migrations_applied(**kwargs):
            # This import may be here for the correct initialization of the App
            from api.tasks import (  # pylint: disable=import-outside-toplevel
                programs,
                providers,
            )

            providers.assign_admin_group()
            programs.assign_run_permission()

        post_migrate.connect(on_migrations_applied)
