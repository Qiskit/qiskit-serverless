"""Proxies for database models"""

import requests

from django.conf import settings
from django.contrib.auth import get_user_model

from api.utils import safe_request


class QuantumUserProxy(get_user_model()):
    """
    This proxy manages custom values for QuantumUser users like instances.
    """

    instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"

    class Meta:  # pylint: disable=too-few-public-methods
        """Proxy configuration"""

        proxy = True

    def get_network(self, access_token: str):
        """
        Obtain network configuration for a specific user:

        Returns:
        network: {
            name: str,
            groups: {
                str: {
                    name:
                    projects: {
                        str: {
                            name: str
                        }
                    }
                }
            }
        }
        """
        if self.instances_url is None:
            return []

        return safe_request(
            request=lambda: requests.get(
                self.instances_url,
                headers={"Authorization": access_token},
                timeout=60,
            )
        )

    def get_instances_from_network(self, access_token: str) -> list[str]:
        """
        Returns an array of instances from network configuration.
        """
        instances = []

        network = self.get_network(access_token)
        if network:  # pylint: disable=too-many-nested-blocks
            for hub in network:
                groups = hub.get("groups")
                if not groups:
                    instances.append(hub.get("name"))
                else:
                    for group in groups.values():
                        projects = group.get("projects")
                        if not projects:
                            instances.append(f"{hub.get('name')}/{group.get('name')}")
                        else:
                            for project in projects.values():
                                instances.append(
                                    f"{hub.get('name')}/{group.get('name')}/{project.get('name')}"
                                )

        return instances
