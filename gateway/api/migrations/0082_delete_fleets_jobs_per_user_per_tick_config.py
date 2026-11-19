from django.db import migrations


def delete_config(apps, schema_editor):
    Config = apps.get_model("api", "Config")
    Config.objects.filter(name="scheduler.fleets.jobs_per_user_per_tick").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0081_blockedcloudresource_reason_region"),
    ]

    operations = [
        migrations.RunPython(delete_config, migrations.RunPython.noop),
    ]
