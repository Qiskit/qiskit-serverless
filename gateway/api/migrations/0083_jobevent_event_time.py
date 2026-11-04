from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0082_delete_fleets_jobs_per_user_per_tick_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobevent",
            name="event_time",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
