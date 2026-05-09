from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0050_unique_program_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="codeengineproject",
            name="project_id",
            field=models.CharField(max_length=255, help_text="IBM Code Engine project UUID"),
        ),
        migrations.AddField(
            model_name="codeengineproject",
            name="zone",
            field=models.CharField(
                blank=True,
                help_text="Availability zone this project is pinned to (e.g. us-east-1)",
                max_length=64,
                null=True,
                unique=True,
            ),
        ),
    ]
