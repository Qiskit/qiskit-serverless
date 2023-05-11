"""Errors utilities."""
from typing import Optional


def format_err_msg(
    message: str, code: Optional[int] = None, extra: Optional[str] = None
):
    """Formats error message.

    Args:
        message: main body of message
        code: error code
        extra: extra information about error

    Returns:
        formatted string
    """
    result = f"\nMessage: {message}"
    if code:
        result += f"\nCode: {code}"
    if extra:
        result += f"\nInfo: {extra}"
    return result
