# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Migration operations that are safe to retry."""

from django.contrib.postgres.operations import AddIndexConcurrently


class AddIndexConcurrentlyRetryable(AddIndexConcurrently):
    """AddIndexConcurrently that first drops a leftover invalid index with the same name.

    A cancelled CREATE INDEX CONCURRENTLY leaves an invalid index behind and the migration is not
    recorded, so every later run would fail with "relation already exists". Here that leftover is
    dropped (concurrently) and the index is built again. A valid index with the same name is not
    touched. Off PostgreSQL (the tests run on SQLite) it falls back to a plain AddIndex.

    The migration must set ``atomic = False``, because CONCURRENTLY cannot run in a transaction::

        class Migration(migrations.Migration):
            atomic = False

            operations = [
                AddIndexConcurrentlyRetryable(
                    model_name="job",
                    index=models.Index(fields=["some_field"], name="job_some_field_idx"),
                ),
            ]
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        if schema_editor.connection.vendor != "postgresql":
            schema_editor.add_index(model, self.index)
            return
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_index WHERE indexrelid = to_regclass(%s) AND NOT indisvalid",
                [self.index.name],
            )
            has_invalid_leftover = cursor.fetchone() is not None
        if has_invalid_leftover:
            schema_editor.execute(f"DROP INDEX CONCURRENTLY {schema_editor.quote_name(self.index.name)}")
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            model = from_state.apps.get_model(app_label, self.model_name)
            if self.allow_migrate_model(schema_editor.connection.alias, model):
                schema_editor.remove_index(model, self.index)
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)
