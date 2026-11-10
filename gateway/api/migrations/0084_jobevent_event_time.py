from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0083_alter_job_runner_alter_program_runner"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobevent",
            name="event_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
