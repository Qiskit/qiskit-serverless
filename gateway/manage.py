#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import logging
import os
import sys

logger = logging.getLogger("main")


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    logger.info(f"[BOOT] Executing command manage.py {sys.argv[1] if len(sys.argv) > 1 else ''}")
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
