"""Scheduling related functions."""
from api.models import Job, Program


def is_hitting_limits(user) -> bool:
    """Checks if given user is hitting limits on a programs execution.

    Current limits are:
    - max compute resources that cluster can handle
    - max number of program allowed per user

    Args:
        user: user session

    Returns:
        true if user is hitting the limits.
    """
    pass


def upsert_program(serializer) -> Program:
    """Upserts program.

    Args:
        serializer: program serializer with data attached.

    Returns:
        upserted program
    """
    pass


def execute_program(program, user) -> Job:
    """Executes program.

    Args:
        program: program to execute
        user: user session

    Returns:
        job of program execution
    """
    pass
