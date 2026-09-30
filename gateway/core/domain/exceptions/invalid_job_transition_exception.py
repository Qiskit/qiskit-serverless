"""Invalid job transition exception is raised by JobTransitionService when
the new status is not valid (check JobTransitionService.VALID_TRANSITIONS)"""


class InvalidJobTransitionException(Exception):
    """Raised by JobTransitionService for a status transition not in its VALID_TRANSITIONS (like FAILED to RUNNING)"""
