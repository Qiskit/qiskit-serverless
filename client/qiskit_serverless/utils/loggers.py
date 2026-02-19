# This code is a Qiskit project.
#
# (C) Copyright IBM 2024.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
======================================================================
Loggers utilities (:mod:`qiskit_serverless.utils.loggers`)
======================================================================

.. currentmodule:: qiskit_serverless.utils.loggers
"""

import logging


class PrefixFormatter(logging.Formatter):
    """Formater to add a prefix to logger and split in lines."""

    def __init__(self, prefix, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefix = prefix

    def format(self, record):
        """format the record to add a prefix to logger and split in lines."""
        original_msg = record.getMessage()
        lines = original_msg.splitlines()

        formatted_lines = []
        for line in lines:
            temp = logging.LogRecord(
                name=record.name,
                level=record.levelno,
                pathname=record.pathname,
                lineno=record.lineno,
                msg=line,
                args=None,
                exc_info=None,
            )

            base = super().format(temp)
            formatted_lines.append(f"{self.prefix} {base}")

        return "\n".join(formatted_lines)


def _create_logger(name, prefix):
    """creates a logger with the prefix formatter"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = PrefixFormatter(prefix=prefix, fmt="%(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def get_logger():
    """creates a logger for the user public logs"""
    return _create_logger("user", "[PUBLIC]")


def get_provider_logger():
    """creates a logger for the provider private logs"""
    return _create_logger("provider", "[PRIVATE]")
