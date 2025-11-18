"""
Repository implementation for ProgramHistory model
"""
import logging
from typing import Optional

from api.models import ProgramHistory, Program, Group


logger = logging.getLogger("gateway")


class ProgramHistoryRepository:
    """
    The main objective of this class is to manage the access to the ProgramHistory model
    """

    def get_latest_log_entry_for_program(self, program: Program):
        """
        Get the most recent LogEntry for a Program.

        This should be called immediately after a change to capture the LogEntry
        that was just created by Django admin.

        Args:
          - program: Program instance

        Returns:
          - LogEntry or None if no entry found
        """
        from django.contrib.admin.models import LogEntry
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(Program)
        return (
            LogEntry.objects.filter(
                content_type=content_type, object_id=str(program.pk)
            )
            .order_by("-action_time")
            .first()
        )

    def create_history_entry(
        self,
        program: Program,
        group: Group,
        field_name: str,
        action: str,
    ) -> ProgramHistory:
        """
        Creates a history entry for a program field change.

        Args:
          - program: Program instance
          - group: Group being added/removed
          - field_name: Field name (use ProgramHistory.PROGRAM_FIELD_INSTANCES or PROGRAM_FIELD_TRIAL_INSTANCES)
          - action: Action type (use ProgramHistory.ADD or ProgramHistory.REMOVE)

        Returns:
          - ProgramHistory: the created history entry
        """
        log_entry = self.get_latest_log_entry_for_program(program)

        history_entry = ProgramHistory(
            function=program,
            log_entry=log_entry,
            field_name=field_name,
            action=action,
            value=str(group.id),
            description=group.name,
        )
        history_entry.save()

        logger.debug(
            "Created %s history entry for program [%s], field [%s], group [%s]",
            action,
            program.id,
            field_name,
            group.name,
        )
        return history_entry

    def get_by_program(self, program: Program):
        """
        Returns all history entries for a specific program.

        Args:
          - program: Program instance

        Returns:
          - QuerySet: ProgramHistory entries for the program
        """
        return ProgramHistory.objects.filter(function=program).order_by("-created_at")

    def get_by_program_and_field(self, program: Program, field_name: str):
        """
        Returns history entries for a specific program and field.

        Args:
          - program: Program instance
          - field_name: Field name to filter by

        Returns:
          - QuerySet: ProgramHistory entries matching the criteria
        """
        return ProgramHistory.objects.filter(
            function=program, field_name=field_name
        ).order_by("-created_at")

    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        """
        Retrieves a Group by ID.

        Args:
          - group_id: Group primary key

        Returns:
          - Group | None: the group if found, None otherwise
        """
        try:
            return Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            logger.warning("Group [%s] does not exist.", group_id)
            return None
