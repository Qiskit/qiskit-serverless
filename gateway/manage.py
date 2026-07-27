#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import logging
import os
import sys

logger = logging.getLogger("main")


def _load_local_env():
    """Load a local .env file when ENV_FILE points to one.

    Opt-in only: nothing is loaded unless ENV_FILE is set, so docker compose and
    Kubernetes (which do not set it) keep getting their config from real
    environment variables. Meant for local development, e.g.
    `ENV_FILE=.env.staging python manage.py runserver`.
    """
    env_file = os.environ.get("ENV_FILE")
    if not env_file:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), env_file)
    if os.path.exists(env_path):
        # override=False: real shell env vars still win over the file.
        load_dotenv(env_path, override=False)
        logger.info(f"[BOOT] Loaded local env file {env_file}")


def main():
    """Run administrative tasks."""
    _load_local_env()
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
