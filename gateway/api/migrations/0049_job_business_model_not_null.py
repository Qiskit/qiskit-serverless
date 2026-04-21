from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0048_job_business_model_backfill"),
    ]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="business_model",
            field=models.CharField(default="subsidised", max_length=50),
        ),
    ]
