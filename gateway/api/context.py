"""User context management using ContextVars."""

from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional

from django.contrib.auth import get_user_model

User = get_user_model()

# ContextVar to store the current user
_current_user: ContextVar[Optional[User]] = ContextVar("current_user", default=None)


def get_current_user() -> Optional[User]:
    """
    Get the current user from the context.

    Returns:
        The current user or None if user is not set in the context.
    """
    return _current_user.get()


def set_current_user(user: Optional[User]) -> None:
    """
    Set the current user in the context.

    Args:
        user: The user to set as current, or None to clear.
    """
    _current_user.set(user)


@contextmanager
def impersonate(user: Optional[User]):
    """
    Context manager to temporarily impersonate a user.

    This is primarily useful for testing scenarios where you need to
    simulate actions performed by a specific user.

    Args:
        user: The user to impersonate, or None to clear the user context.

    Example:
        with impersonate(some_user):
            # Code here will see some_user as the current user
            do_something()
    """
    previous_user = get_current_user()
    set_current_user(user)
    try:
        yield
    finally:
        set_current_user(previous_user)
