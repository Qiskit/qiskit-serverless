from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0046_alter_config_options_alter_jobevent_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="business_model",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
