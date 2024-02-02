# Generated by Django 4.2.2 on 2023-11-13 20:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0011_jobconfig_job_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobconfig",
            name="python_version",
            field=models.CharField(
                blank=True,
                choices=[
                    ("py38", "Version 3.8"),
                    ("py39", "Version 3.9"),
                    ("py310", "Version 3.10"),
                ],
                max_length=6,
                null=True,
            ),
        ),
    ]