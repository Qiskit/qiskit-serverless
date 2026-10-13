# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Per-region Event Streams connection settings, shared by the producers and the consumers so the
two can never disagree on which regions exist or how to connect to them.

Configured from Django settings (main/settings.py):
  settings.EVENT_STREAMS_MAIN_REGION:       main region (default: us-east)
  settings.EVENT_STREAMS_BOOTSTRAP_SERVERS: comma-separated broker list (main region)
  settings.EVENT_STREAMS_API_KEY:           SASL/PLAIN password (main region)
  settings.EVENT_STREAMS_USER:              SASL/PLAIN username (main region)
  settings.EVENT_STREAMS_REGIONS:           {region: {bootstrap_servers, api_key, user}}
    for additional regions, discovered from suffixed environment variables at settings import time
"""

from __future__ import annotations

from django.conf import settings


def region_configs() -> dict[str, dict[str, str]]:
    """Every configured region's {bootstrap_servers, api_key, user}, the main region first.

    The suffixed regions come last, so one of them declaring the main region wins.
    """
    return {
        settings.EVENT_STREAMS_MAIN_REGION: {
            "bootstrap_servers": settings.EVENT_STREAMS_BOOTSTRAP_SERVERS,
            "api_key": settings.EVENT_STREAMS_API_KEY,
            "user": settings.EVENT_STREAMS_USER,
        },
        **settings.EVENT_STREAMS_REGIONS,
    }


def sasl_config(config: dict[str, str]) -> dict[str, str]:
    """The librdkafka connection properties for one region's config."""
    return {
        "bootstrap.servers": config["bootstrap_servers"],
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "PLAIN",
        "sasl.username": config["user"],
        "sasl.password": config["api_key"],
    }
