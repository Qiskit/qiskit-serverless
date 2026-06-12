from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0052_job_account_id_job_instance_crn"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="arguments_schema",
            field=models.TextField(blank=True, default="{}", null=False),
        ),
    ]
