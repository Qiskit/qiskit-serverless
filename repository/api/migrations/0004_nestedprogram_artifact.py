# Generated by Django 4.1.6 on 2023-02-15 14:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="nestedprogram",
            name="artifact",
            field=models.FileField(default="1", upload_to="artifacts_%Y_%m_%d"),
            preserve_default=False,
        ),
    ]
