"""Methods for filtering job logs."""

import re


def extract_public_logs(text: str) -> str:
    """
    This filter the logs to get the public ones only.

    Args:
        text: str

    Return:
        str -> The log filtered out
    """
    pattern = re.compile(r"^\[PUBLIC\]", re.IGNORECASE)
    lines = [line[9:] for line in text.splitlines() if pattern.match(line)]
    return "\n".join(lines) + "\n" if lines else ""
