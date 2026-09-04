from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0063_merge_20260902_1720"),
    ]

    operations = [
        # Step 1 of a two-step removal of Job.compute_profile (the transitional
        # string). compute_profile_fk (FK -> ComputeProfile) is the source of
        # truth; readers in this repo now go through Job.compute_profile_id, which
        # reads the FK. Here the field is dropped from Django's state ONLY; the
        # api_job.compute_profile column is left in place so the previous release
        # -- whose Job model still declares the field and lists it in every SELECT
        # -- stays deployable. The real DROP COLUMN happens in a later release,
        # once no release that declares the field can still be deployed (mirrors
        # the Program.default_compute_profile removal, migrations 0057 -> 0058).
        #
        # BLOCKED: this migration must NOT ship until the billing team repoints
        # KafkaEventStreamsClient._build_classical_metric_type
        # (gateway/core/ibm_cloud/event_streams/kafka_event_streams_client.py) off
        # job.compute_profile and onto job.compute_profile_fk.compute_profile_id.
        # That file is owned by another team and is deliberately untouched here;
        # removing the field from the model state while it still reads the string
        # attribute would raise AttributeError when a usage event is built.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="job",
                    name="compute_profile",
                ),
            ],
            database_operations=[],
        ),
    ]
