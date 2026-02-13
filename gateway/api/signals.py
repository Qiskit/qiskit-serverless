"""Signals for api models."""

from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from api.context import get_current_user
from api.repositories.groups import GroupRepository
from api.repositories.program_history import ProgramHistoryRepository
from core.models import Program, ProgramHistory


@receiver(m2m_changed, sender=Program.instances.through)
def handle_program_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """
    Handle changes to Program.instances ManyToMany relationship.

    Args:
        sender: The Program model
        instance: The Program instance
        action: 'pre_add', 'post_add', 'pre_remove', 'post_remove'
        pk_set: Set of primary keys of the Group objects being added/removed
    """
    program_history_repository = ProgramHistoryRepository()
    groups_repository = GroupRepository()

    if action == "post_add":
        history_action = ProgramHistory.ADD
    elif action == "post_remove":
        history_action = ProgramHistory.REMOVE
    else:
        return

    def create_history_entries():
        user = get_current_user()
        for group_id in pk_set:
            group = groups_repository.get_group_by_id(group_id)
            if not group:
                continue
            program_history_repository.create_history_entry(
                program=instance,
                entity_model=group.__class__,
                entity_id=group.id,
                description=group.name,
                field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                action=history_action,
                user=user,
            )

    # Use on_commit to ensure LogEntry is created first
    transaction.on_commit(create_history_entries)


@receiver(m2m_changed, sender=Program.trial_instances.through)
def handle_program_trial_instances_changed(sender, instance, action, pk_set, **kwargs):
    # pylint: disable=unused-argument
    """
    Handle changes to Program.trial_instances ManyToMany relationship.

    Args:
        sender: The Program model
        instance: The Program instance
        action: 'pre_add', 'post_add', 'pre_remove', 'post_remove'
        pk_set: Set of primary keys of the Group objects being added/removed
    """
    program_history_repository = ProgramHistoryRepository()
    groups_repository = GroupRepository()

    if action == "post_add":
        history_action = ProgramHistory.ADD
    elif action == "post_remove":
        history_action = ProgramHistory.REMOVE
    else:
        return

    def create_history_entries():
        user = get_current_user()
        for group_id in pk_set:
            group = groups_repository.get_group_by_id(group_id)
            if not group:
                continue
            program_history_repository.create_history_entry(
                program=instance,
                entity_model=group.__class__,
                entity_id=group.id,
                description=group.name,
                field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                action=history_action,
                user=user,
            )

    transaction.on_commit(create_history_entries)
