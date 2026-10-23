from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0078_job_function_size_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobevent",
            name="occurred_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
