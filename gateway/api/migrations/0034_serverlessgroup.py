# Generated by Django 4.2.19 on 2025-03-07 17:10

import django.contrib.auth.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("api", "0033_job_trial_program_trial_instances_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServerlessGroup",
            fields=[
                (
                    "parent_group",
                    models.OneToOneField(
                        db_column="parent_group",
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="auth.group",
                    ),
                ),
                (
                    "account",
                    models.CharField(
                        blank=True, default=None, max_length=255, null=True
                    ),
                ),
            ],
            bases=("auth.group",),
            managers=[
                ("objects", django.contrib.auth.models.GroupManager()),
            ],
        ),
    ]
