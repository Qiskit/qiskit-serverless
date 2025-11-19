import logging
from typing import Optional

from api.models import ProgramHistory, Program, Group


logger = logging.getLogger("gateway")


class ProgramHistoryRepository:
    def create_history_entry(
        self,
        program: Program,
        entity_model: type,
        entity_id: int,
        description: str,
        field_name: str,
        action: str,
    ) -> ProgramHistory:
        """
        Creates a history entry for a program field change.

        Args:
          - program: Program instance to log the change
          - entity_model: Model class of the related entity (e.g., Group)
          - entity_id: ID of the related entity being added/removed
          - description: Human-readable description of the related entity, like the Group name
          - field_name: Field name (use ProgramHistory.PROGRAM_FIELD_INSTANCES or PROGRAM_FIELD_TRIAL_INSTANCES)
          - action: Action type (use ProgramHistory.ADD or ProgramHistory.REMOVE)

        Returns:
          - ProgramHistory: the created history entry
        """

        history_entry = ProgramHistory(
            program=program,
            field_name=field_name,
            action=action,
            entity=entity_model.__name__,
            entity_id=str(entity_id),
            description=description,
        )
        history_entry.save()
        return history_entry

    def get_group_by_id(self, group_id: int) -> Optional[Group]:
        try:
            return Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            logger.warning("Group [%s] does not exist.", group_id)
            return None
