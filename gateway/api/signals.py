"""Signals for api models."""

from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from api.context import get_current_user
from core.models import Program, ProgramHistory


@receiver(m2m_changed, sender=Program.instances.through)
def handle_program_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """..."""

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
                field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                action=history_action,
                entity=group.__class__.__name__,
                entity_id=str(group.id),
                description=group.name,
                user=user,
            )

    transaction.on_commit(create_history_entries)


@receiver(m2m_changed, sender=Program.trial_instances.through)
def handle_program_trial_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """..."""

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
                field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                action=history_action,
                entity=group.__class__.__name__,
                entity_id=str(group.id),
                description=group.name,
                user=user,
            )

    transaction.on_commit(create_history_entries)
