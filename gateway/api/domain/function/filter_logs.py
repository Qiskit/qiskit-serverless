"""Methods for filtering job logs."""
import re
from typing import Optional


def extract_public_logs(text: str) -> str:
    pattern = re.compile(r"^\[PUBLIC\]", re.IGNORECASE)
    lines = [line[9:] for line in text.splitlines() if pattern.match(line)]
    return "\n".join(lines) + "\n" if lines else ""
