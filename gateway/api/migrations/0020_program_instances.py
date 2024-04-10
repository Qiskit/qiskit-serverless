# Generated by Django 4.2.11 on 2024-04-10 16:38

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0019_alter_job_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="instances",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255),
                blank=True,
                default=list,
                size=None,
            ),
        ),
    ]