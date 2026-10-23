from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop the ``api_job.compute_profile`` column.

    ``0073`` removed the field from Django's state but kept the column, so the
    release before it could still be deployed. This migration drops it for real.
    It adds the field back to the state only, then removes it, so the schema
    editor drops the column. Same pattern as ``0058``.
    """

    dependencies = [
        ("api", "0078_job_function_size_name"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="job",
                    name="compute_profile",
                    field=models.CharField(
                        blank=True,
                        help_text="Code Engine compute profile for Fleets runner (e.g., gx3d-24x120x1a100p)",
                        max_length=255,
                        null=True,
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.RemoveField(
            model_name="job",
            name="compute_profile",
        ),
    ]
