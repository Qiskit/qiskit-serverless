"""
Django management command that syncs a CodeEngineProject from environment variables.

When CE_PROJECT_ID is set in Django settings, this command creates or updates
a CodeEngineProject row with all CE_* settings. Run after migrations:

    migrate_with_lock -> sync_ce_project -> gunicorn
"""

import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import CodeEngineProject

logger = logging.getLogger("sync_ce_project")

_REQUIRED_SETTINGS = {
    "CE_PROJECT_NAME": "CE_PROJECT_NAME",
    "CE_REGION": "CE_REGION",
    "CE_RESOURCE_GROUP_ID": "CE_RESOURCE_GROUP_ID",
    "CE_SUBNET_POOL_ID": "CE_SUBNET_POOL_ID",
    "CE_PDS_NAME_STATE": "CE_PDS_NAME_STATE",
    "CE_PDS_NAME_USERS": "CE_PDS_NAME_USERS",
    "CE_PDS_NAME_PROVIDERS": "CE_PDS_NAME_PROVIDERS",
    "CE_COS_INSTANCE_NAME": "CE_COS_INSTANCE_NAME",
    "CE_COS_KEY_NAME": "CE_COS_KEY_NAME",
    "CE_COS_BUCKET_USER_DATA_NAME": "CE_COS_BUCKET_USER_DATA_NAME",
    "CE_COS_BUCKET_PROVIDER_DATA_NAME": "CE_COS_BUCKET_PROVIDER_DATA_NAME",
}


class Command(BaseCommand):
    """Create or update a CodeEngineProject from CE_* environment variables."""

    help = "Sync CodeEngineProject from CE_* environment variables"

    def handle(self, *args, **options):
        if not settings.CE_PROJECT_ID:
            logger.info("CE_PROJECT_ID not set — skipping CodeEngineProject sync")
            return

        values = {key: getattr(settings, attr) for key, attr in _REQUIRED_SETTINGS.items()}
        missing = [k for k, v in values.items() if not v]
        if missing:
            logger.error("CE_PROJECT_ID is set but missing required settings: %s", ", ".join(missing))
            return

        _, created = CodeEngineProject.objects.update_or_create(
            project_id=settings.CE_PROJECT_ID,
            defaults={
                "project_name": settings.CE_PROJECT_NAME,
                "region": settings.CE_REGION,
                "resource_group_id": settings.CE_RESOURCE_GROUP_ID,
                "subnet_pool_id": settings.CE_SUBNET_POOL_ID,
                "pds_name_state": settings.CE_PDS_NAME_STATE,
                "pds_name_users": settings.CE_PDS_NAME_USERS,
                "pds_name_providers": settings.CE_PDS_NAME_PROVIDERS,
                "cos_instance_name": settings.CE_COS_INSTANCE_NAME,
                "cos_key_name": settings.CE_COS_KEY_NAME,
                "cos_bucket_user_data_name": settings.CE_COS_BUCKET_USER_DATA_NAME,
                "cos_bucket_provider_data_name": settings.CE_COS_BUCKET_PROVIDER_DATA_NAME,
                "active": True,
            },
        )
        action = "Created" if created else "Updated"
        logger.info("%s CodeEngineProject [%s] in region [%s]", action, settings.CE_PROJECT_NAME, settings.CE_REGION)
