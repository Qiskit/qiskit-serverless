# Generated by Django 5.1 on 2024-08-21 18:24

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0029_program_additional_info_program_documentation_url_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AlterField(
            model_name="program",
            name="instances",
            field=models.ManyToManyField(blank=True, to="auth.group"),
        ),
    ]