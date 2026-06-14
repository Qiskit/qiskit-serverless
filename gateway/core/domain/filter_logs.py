"""Methods for filtering job logs."""

import re
from typing import Iterable

public_pattern = re.compile(r"^\[PUBLIC\]", re.IGNORECASE)
private_pattern = re.compile(r"^\[PRIVATE\]", re.IGNORECASE)


def filter_logs_with_public_tags(lines: Iterable[str]) -> str:
    """Keep only [PUBLIC] lines and strip the prefix tag."""
    result = [line[9:] for line in lines if public_pattern.match(line)]
    return "\n".join(result) + "\n" if result else ""


def filter_logs_with_non_public_tags(lines: Iterable[str]) -> str:
    """Keep all non-[PUBLIC] lines; strip [PRIVATE] prefix from those that have it."""

    def strip_private(line: str) -> str:
        return line[10:] if private_pattern.match(line) else line

    result = [strip_private(line) for line in lines if not public_pattern.match(line)]
    return "\n".join(result) + "\n" if result else ""


def remove_prefix_tags_in_logs(lines: Iterable[str]) -> str:
    """Strip [PUBLIC] or [PRIVATE] prefix from all lines, keeping every line."""

    def strip_tag(line: str) -> str:
        if public_pattern.match(line):
            return line[9:]
        if private_pattern.match(line):
            return line[10:]
        return line

    result = [strip_tag(line) for line in lines]
    return "\n".join(result) + "\n" if result else ""
