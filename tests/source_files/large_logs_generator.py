import os

from qiskit_serverless import get_logger

logger = get_logger()

size_mb = int(os.environ.get("LOGS_SIZE_MB", "500"))
line = "X" * 1000  # ~1 KB per entry

target_bytes = size_mb * 1024 * 1024
written = 0
count = 0

while written < target_bytes:
    logger.info(line)
    written += 1024
    count += 1

print(f"LARGE_LOGS_DONE lines={count} size_mb={size_mb}")
