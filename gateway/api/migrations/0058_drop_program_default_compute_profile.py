from django.db import migrations, models


class Migration(migrations.Migration):
    """Drop the ``api_program.default_compute_profile`` column.

    Migration ``0057`` removed the field from Django's state but left the column
    in the database, so that the release before it stayed deployable: that release
    still declares the field on its ``Program`` model, and Django lists every
    declared column in each ``SELECT``.

    This migration does the actual drop, and must only ship once no release that
    declares the field can still be deployed. It first puts the field back into
    the state without touching the database, then removes it for real, so the
    column is dropped through the schema editor instead of hand-written SQL.
    """

    dependencies = [
        ("api", "0057_computeprofile_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="program",
                    name="default_compute_profile",
                    field=models.CharField(blank=True, max_length=255, null=True),
                ),
            ],
            database_operations=[],
        ),
        migrations.RemoveField(
            model_name="program",
            name="default_compute_profile",
        ),
    ]
