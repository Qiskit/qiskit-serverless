import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Rename ``Job.compute_profile_fk`` to ``Job.compute_profile`` in Django's model state only.

    The column keeps its name through ``db_column="compute_profile_fk_id"``, so no SQL runs.
    Pods on the previous release still list ``compute_profile_fk_id`` in every
    ``SELECT``/``INSERT`` on ``api_job`` during a rolling deploy, and a real
    ``RENAME COLUMN`` would break them. Rolling the code back needs no reverse migration.
    """

    dependencies = [
        ("api", "0083_alter_job_runner_alter_program_runner"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="job",
                    old_name="compute_profile_fk",
                    new_name="compute_profile",
                ),
                migrations.AlterField(
                    model_name="job",
                    name="compute_profile",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="compute_profile_fk_id",
                        help_text="Compute profile used by the job, captured at creation time so the historical compute profile is preserved even if the profile changes later.",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="jobs",
                        to="api.computeprofile",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
