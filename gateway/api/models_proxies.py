"""Proxies for database models"""

import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from api.utils import safe_request


class QuantumUserProxy(get_user_model()):
    """
    This proxy manages custom values for QuantumUser users like instances.
    """

    instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"

    class Meta:  # pylint: disable=too-few-public-methods
        """Proxy configuration"""

        proxy = True

    def __get_network(self, access_token: str):
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

    def __get_instances_from_network(self, network) -> list[str]:
        """
        Returns an array of instances from network configuration.
        """
        instances = []
        if network:
            for hub in network:
                groups = hub.get("groups")
                instances.append(hub.get("name"))
                for group in groups.values():
                    projects = group.get("projects")
                    instances.append(f"{hub.get('name')}/{group.get('name')}")
                    for project in projects.values():
                        instances.append(
                            f"{hub.get('name')}/{group.get('name')}/{project.get('name')}"
                        )
        return instances

    def update_groups(self, access_token):
        """
        This method obtains the instances of a user from IQP Network User information
        and update Django Groups with that information.
        """
        network = self.__get_network(access_token)
        instances = self.__get_instances_from_network(network)

        self.groups.clear()
        for instance in instances:
            try:
                group = Group.objects.get(name=instance)
            except Group.DoesNotExist:
                group = Group.objects.create(name=instance)
            group.user_set.add(self)

        groups_names = self.groups.values_list("name", flat=True).distinct()
        groups_names_list = list(groups_names)

        print("INFORMACION DE LOS GRUPOS DEL USUARIO ----------------------")
        print(instances)
        print(groups_names_list)

        return True
