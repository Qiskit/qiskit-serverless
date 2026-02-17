"""Methods for filtering job logs."""

import re

public_pattern = re.compile(r"^\[PUBLIC\]", re.IGNORECASE)
private_pattern = re.compile(r"^\[PRIVATE\]", re.IGNORECASE)


def filter_logs_with_public_tags(text: str) -> str:
    """
    This filter the logs to get the public lines only.

    Args:
        text: str

    Return:
        str -> The log filtered out
    """
    lines = [line[9:] for line in text.splitlines() if public_pattern.match(line)]
    return "\n".join(lines) + "\n" if lines else ""


def filter_logs_with_non_public_tags(text: str) -> str:
    """
    This filter the logs to get the private and non tagged lines only.

    Args:
        text: str

    Return:
        str -> The log filtered out
    """

    def remove_prefix_tag(line: str) -> str:
        if private_pattern.match(line):
            return line[10:]
        return line

    lines = [
        remove_prefix_tag(line)
        for line in text.splitlines()
        if not public_pattern.match(line)
    ]
    return "\n".join(lines) + "\n" if lines else ""


def remove_prefix_tags_in_logs(text: str) -> str:
    """
    Remove all the tags that starts with [PUBLIC] or [PRIVATE].

    Args:
        text: str

    Return:
        str -> The log filtered out
    """

    def remove_prefix_tag(line: str) -> str:
        if public_pattern.match(line):
            return line[9:]
        if private_pattern.match(line):
            return line[10:]
        return line

    lines = [remove_prefix_tag(line) for line in text.splitlines()]
    return "\n".join(lines) + "\n" if lines else ""
