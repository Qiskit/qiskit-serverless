from django.db import migrations
from django.db.models import Case, Value, When


def backfill_business_model(apps, schema_editor):
    Job = apps.get_model("api", "Job")
    Job.objects.update(
        business_model=Case(
            When(trial=True, then=Value("trial")),
            default=Value("subsidised"),
        )
    )


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0047_job_business_model"),
    ]

    operations = [
        migrations.RunPython(backfill_business_model, migrations.RunPython.noop),
    ]
