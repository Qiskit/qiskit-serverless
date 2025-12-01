"""
Repository implementation for ProgramHistory model
"""

import logging
from typing import Optional

from django.contrib.auth import get_user_model
from api.models import ProgramHistory, Program

logger = logging.getLogger("gateway")
User = get_user_model()


class ProgramHistoryRepository:
    """
    Repository to manage all read and write operations on the Groups table.
    """

    def create_history_entry(
        self,
        *,
        program: Program,
        entity_model: type,
        entity_id: int,
        description: str,
        field_name: str,
        action: str,
        user: Optional[User] = None,
    ) -> ProgramHistory:
        """
        Creates a history entry for a program change in a relationship.

        Args:
          - program: Program instance to log the change
          - entity_model: Model class of the related entity (e.g., Group)
          - entity_id: ID of the related entity being added/removed
          - description: Human-readable description of the related entity, like the group name
          - field_name: Field name (use ProgramHistory.PROGRAM_FIELD_INSTANCES
              or PROGRAM_FIELD_TRIAL_INSTANCES)
          - action: Action type (use ProgramHistory.ADD or ProgramHistory.REMOVE)
          - user: User who made the change (optional)

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
            user=user,
        )
        history_entry.save()
        return history_entry
