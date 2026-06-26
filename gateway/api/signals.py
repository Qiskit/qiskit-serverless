"""Signals for api models."""

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from api.context import get_current_user
from core.models import Program, ProgramHistory


def _handle_program_field_changed(instance, action, pk_set, field_name):
    if action == "post_add":
        history_action = ProgramHistory.ADD
    elif action == "post_remove":
        history_action = ProgramHistory.REMOVE
    else:
        return

    def create_history_entries():
        user = get_current_user()
        for group_id in pk_set:
            group = Group.objects.filter(id=group_id).first()
            if not group:
                continue
            ProgramHistory.objects.create(
                program=instance,
                field_name=field_name,
                action=history_action,
                entity=group.__class__.__name__,
                entity_id=str(group.id),
                description=group.name,
                user=user,
            )

    transaction.on_commit(create_history_entries)


@receiver(m2m_changed, sender=Program.instances.through)
def handle_program_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """Handle changes to Program.instances ManyToMany relationship."""
    _handle_program_field_changed(instance, action, pk_set, ProgramHistory.PROGRAM_FIELD_INSTANCES)


@receiver(m2m_changed, sender=Program.trial_instances.through)
def handle_program_trial_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """Handle changes to Program.trial_instances ManyToMany relationship."""
    _handle_program_field_changed(instance, action, pk_set, ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES)
