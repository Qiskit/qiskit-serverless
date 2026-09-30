from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0063_merge_20260902_1720"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["fleet_id"], name="job_fleet_id_idx"),
        ),
    ]
