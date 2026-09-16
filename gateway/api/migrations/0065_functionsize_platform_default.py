# Generated migration for FunctionSize platform-default support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0064_job_fleet_id_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="functionsize",
            name="function",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="function_sizes",
                to="core.program",
            ),
        ),
        migrations.AddConstraint(
            model_name="functionsize",
            constraint=models.UniqueConstraint(
                condition=models.Q(("function__isnull", True)),
                fields=["function_size"],
                name="unique_platform_default_function_size",
            ),
        ),
    ]
