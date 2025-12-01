"""Methods for filtering job logs."""
import re
from typing import Optional


def extract_public_logs(text: str) -> str:
    """
    This filter the logs to get the public ones only.

    Args:
        text: str

    Return:
        str -> The log filtered out
    """
    pattern = re.compile(
        r"^(?:\[(?P<type>PUBLIC|PRIVATE)\]\s+)?[^:]+:[A-Z]+:"
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}:",
        re.IGNORECASE | re.MULTILINE,
    )

    logs: str = ""
    current_block: Optional[list[str]] = None
    current_type: Optional[str] = None

    for line in text.splitlines(True):
        re_match = pattern.match(line)
        if re_match:
            if current_block is not None and current_type == "PUBLIC":
                logs += "".join(current_block)

            log_type = (
                re_match.group("type").upper() if re_match.group("type") else None
            )
            current_block = [line]
            current_type = log_type
        else:
            if current_block is not None and current_type == "PUBLIC":
                current_block.append(line)

    if current_block is not None and current_type == "PUBLIC":
        logs += "".join(current_block)

    return logs
