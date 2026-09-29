"""Invalid job transition exception is raised by job.change_status when
the new status is not valid (check the VALID_TRANSITIONS map)"""


class InvalidJobTransitionException(Exception):
    """Raised by Job.change_status for a status transition not in Job.VALID_TRANSITIONS (like FAILED to RUNNING)"""
