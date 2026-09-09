from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class AddIndexConcurrentlyOrPlain(AddIndexConcurrently):
    """AddIndexConcurrently, but falls back to a plain (locking) AddIndex off PostgreSQL.

    django.contrib.postgres.operations.AddIndexConcurrently always calls
    schema_editor.add_index(model, index, concurrently=True), which the SQLite backend used by
    the test suite doesn't accept at all. CONCURRENTLY only matters for a live PostgreSQL table
    anyway, so a plain index add is a fine substitute everywhere else.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            model = to_state.apps.get_model(app_label, self.model_name)
            if self.allow_migrate_model(schema_editor.connection.alias, model):
                schema_editor.add_index(model, self.index)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            model = from_state.apps.get_model(app_label, self.model_name)
            if self.allow_migrate_model(schema_editor.connection.alias, model):
                schema_editor.remove_index(model, self.index)
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("api", "0063_merge_20260902_1720"),
    ]

    operations = [
        AddIndexConcurrentlyOrPlain(
            model_name="job",
            index=models.Index(fields=["fleet_id"], name="job_fleet_id_idx"),
        ),
    ]
