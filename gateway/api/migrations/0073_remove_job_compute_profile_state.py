from django.db import migrations


class Migration(migrations.Migration):
    """Remove ``api_job.compute_profile`` from Django's model state only.

    The column and all its historical data stay in the database, so a release
    before this one stays deployable: its ``Job`` model still declares the
    field, and Django lists every declared column in each ``SELECT``/``INSERT``.
    The real ``DROP COLUMN`` happens in a later release, once no release that
    declares the field can still be deployed. Same pattern as ``0057``
    (``Program.default_compute_profile``) and ``0058`` (its real drop).
    """

    dependencies = [
        ("api", "0072_outbox_retry_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="job",
                    name="compute_profile",
                ),
            ],
            database_operations=[],
        ),
    ]
