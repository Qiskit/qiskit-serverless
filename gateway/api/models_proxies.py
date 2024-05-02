"""Proxies for database models"""

from typing import List
import logging
import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from api.utils import safe_request, remove_duplicates_from_list


logger = logging.getLogger("gateway.authentication")


class QuantumUserProxy(get_user_model()):  # pylint: disable=too-few-public-methods
    """
    This proxy manages custom values for QuantumUser users like instances.
    """

    instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"

    class Meta:  # pylint: disable=too-few-public-methods
        """Proxy configuration"""

        proxy = True

    def _get_network(self, access_token: str):
        """Obtain network configuration for a specific user:
        Args:
            access_token: IQP user token

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
        logger.info("Get Network information from [%s]", self.instances_url)
        if self.instances_url is None:
            return []

        return safe_request(
            request=lambda: requests.get(
                self.instances_url,
                headers={"Authorization": access_token},
                timeout=60,
            )
        )

    def _get_instances_from_network(self, network) -> List[str]:
        """
        Returns an array of instances from network configuration.
        Args:
            network: Quantum User IQP Network configuration

        Returns:
            List of instances, ex:
            ["hub/group/project"] -> ["hub", "hub/project", "hub/project/group"]
        """
        instances = []
        if network:  # pylint: disable=too-many-nested-blocks
            logger.info("Network exists, generate instances from network")
            for hub in network:
                instances.append(hub.get("name"))
                groups = hub.get("groups")
                if groups:
                    for group in groups.values():
                        instances.append(f"{hub.get('name')}/{group.get('name')}")
                        projects = group.get("projects")
                        if projects:
                            for project in projects.values():
                                instances.append(
                                    f"{hub.get('name')}/{group.get('name')}/{project.get('name')}"
                                )
        return instances

    def update_groups(self, access_token) -> None:
        """
        This method obtains the instances of a user from IQP Network User information
        and update Django Groups with that information.
        Args:
            access_token: IQP user token
        """
        network = self._get_network(access_token)
        instances = self._get_instances_from_network(network)

        # Initially the list generated should not contain duplicates
        # but this is just to sanitize the entry
        logger.info("Remove duplicates from instances")
        unique_instances = remove_duplicates_from_list(instances)

        logger.info("Clean user groups before update them")
        self.groups.clear()

        logger.info("Update [%s] groups", len(unique_instances))
        view_program = Permission.objects.get(codename="view_program")
        for instance in unique_instances:
            group, created = Group.objects.get_or_create(name=instance)
            if created:
                logger.info("New group created")
                group.permissions.add(view_program)
            group.user_set.add(self)
