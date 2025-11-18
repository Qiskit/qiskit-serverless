"""Signals for api models."""

import logging
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from api.models import Program, ProgramHistory
from api.repositories.program_history import ProgramHistoryRepository

logger = logging.getLogger(__name__)

# Debug: Log when signals module is loaded
logger.info(
    f"Loading signals module, Program.instances.through = {Program.instances.through}"
)


@receiver(m2m_changed, sender=Program.instances.through)
def handle_program_instances_changed(sender, instance, action, pk_set, **kwargs):
    """
    Handle changes to Program.instances ManyToMany relationship.

    Args:
        sender: The intermediate model for the m2m field
        instance: The Program instance
        action: The type of update ('pre_add', 'post_add', 'pre_remove', 'post_remove', etc.)
        pk_set: Set of primary keys of the Group objects being added/removed
    """
    repository = ProgramHistoryRepository()

    if action == "post_add":
        history_action = ProgramHistory.ADD
    elif action == "post_remove":
        history_action = ProgramHistory.REMOVE
    else:
        return

    def create_history_entries():
        for group_id in pk_set:
            group = repository.get_group_by_id(group_id)
            if group:
                repository.create_history_entry(
                    program=instance,
                    group=group,
                    field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                    action=history_action,
                )

    # Use on_commit to ensure LogEntry is created first
    transaction.on_commit(create_history_entries)


@receiver(m2m_changed, sender=Program.trial_instances.through)
def handle_program_trial_instances_changed(sender, instance, action, pk_set, **kwargs):
    """
    Handle changes to Program.trial_instances ManyToMany relationship.

    Args:
        sender: The intermediate model for the m2m field
        instance: The Program instance
        action: The type of update ('pre_add', 'post_add', 'pre_remove', 'post_remove', etc.)
        pk_set: Set of primary keys of the Group objects being added/removed
    """
    # Debug: Log ALL actions
    logger.info(
        f"[SIGNAL DEBUG] Action: {action}, Program: {instance.id}, pk_set: {pk_set}"
    )
    print(f"[SIGNAL DEBUG] Action: {action}, Program: {instance.id}, pk_set: {pk_set}")

    repository = ProgramHistoryRepository()

    if action == "post_add":
        history_action = ProgramHistory.ADD
    elif action == "post_remove":
        history_action = ProgramHistory.REMOVE
    else:
        return

    def create_history_entries():
        for group_id in pk_set:
            group = repository.get_group_by_id(group_id)
            if group:
                repository.create_history_entry(
                    program=instance,
                    group=group,
                    field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                    action=history_action,
                )

    transaction.on_commit(create_history_entries)
