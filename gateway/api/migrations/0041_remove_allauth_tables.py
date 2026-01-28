"""
Migration to remove django-allauth tables that are no longer used.

This migration cleans up tables from the 'account' and 'socialaccount' apps
that were part of django-allauth, which has been removed from the project.
"""

from django.db import migrations


def remove_allauth_tables(apps, schema_editor):
    """Remove allauth tables if they exist."""
    # Skip in SQLite (tests). Allauth and socialaccount tables are never created
    if schema_editor.connection.vendor == "sqlite":
        return

    tables = [
        "socialaccount_socialtoken",
        "socialaccount_socialapp_sites",
        "socialaccount_socialapp",
        "socialaccount_socialaccount",
        "account_emailconfirmation",
        "account_emailaddress",
    ]

    with schema_editor.connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

        cursor.execute(
            "DELETE FROM django_migrations WHERE app IN ('account', 'socialaccount')"
        )


def reverse_noop(apps, schema_editor):
    """No-op reverse migration"""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0040_programhistory"),
    ]

    operations = [
        migrations.RunPython(remove_allauth_tables, reverse_noop),
    ]
