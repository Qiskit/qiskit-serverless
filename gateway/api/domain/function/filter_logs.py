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
    pattern = re.compile(
        r"^[\[(?P<type>PUBLIC|PRIVATE)\]\s+][^:]+:[A-Z]+:"
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}:",
        re.IGNORECASE | re.MULTILINE,
    )

    logs: str = ""
    current_block: list[str] = None
    current_type: str = None

    for line in text.splitlines(True):
        m = pattern.match(line)
        if m:
            if current_block is not None and current_type == "PUBLIC":
                logs += "".join(current_block)

            log_type = m.group("type").upper()
            current_block = [line]
            current_type = log_type
        else:
            if current_block is not None and current_type == "PUBLIC":
                current_block.append(line)

    if current_block is not None and current_type == "PUBLIC":
        logs += "".join(current_block)

    return logs
