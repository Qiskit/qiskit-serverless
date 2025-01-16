# Generated by Django 4.2.16 on 2025-01-16 16:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("api", "0032_computeresource_gpu_job_gpu"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="trial_instances",
            field=models.ManyToManyField(
                blank=True, related_name="program_trial_instances", to="auth.group"
            ),
        ),
        migrations.AlterField(
            model_name="program",
            name="instances",
            field=models.ManyToManyField(
                blank=True, related_name="program_instances", to="auth.group"
            ),
        ),
    ]
