from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0046_alter_config_options_alter_jobevent_options_and_more")]

    operations = [
        migrations.AddField(
            model_name="program",
            name="platform_id",
            field=models.CharField(blank=True, max_length=511, null=True, unique=True),
        ),
        migrations.RunSQL(
            sql="""
                UPDATE api_program
                SET platform_id = (
                    SELECT ap.name || '.' || api_program.title
                    FROM api_provider ap
                    WHERE ap.id = api_program.provider_id
                )
                WHERE provider_id IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
