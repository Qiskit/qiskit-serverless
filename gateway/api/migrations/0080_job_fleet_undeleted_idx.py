from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class AddIndexConcurrentlyOnPostgres(AddIndexConcurrently):
    """CREATE INDEX CONCURRENTLY on PostgreSQL, so api_job is not locked; a plain index elsewhere (the sqlite tests)."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        else:
            migrations.AddIndex.database_forwards(self, app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)
        else:
            migrations.AddIndex.database_backwards(self, app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("api", "0079_job_fleet_deleted_at"),
    ]

    operations = [
        AddIndexConcurrentlyOnPostgres(
            model_name="job",
            index=models.Index(
                condition=models.Q(
                    ("fleet_deleted_at__isnull", True), ("fleet_id__isnull", False), ("runner", "fleets")
                ),
                fields=["updated"],
                name="job_fleet_undeleted_idx",
            ),
        ),
    ]
