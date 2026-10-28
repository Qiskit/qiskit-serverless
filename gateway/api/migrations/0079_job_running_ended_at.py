from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0078_job_function_size_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="running_ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
