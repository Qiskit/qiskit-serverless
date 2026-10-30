from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0081_blockedcloudresource_reason_region"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="running_ended_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
