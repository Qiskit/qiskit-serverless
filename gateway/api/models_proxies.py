import requests

from dataclasses import dataclass
from django.conf import settings
from django.contrib.auth import get_user_model
from typing import Dict, List

from api.utils import safe_request


@dataclass
class IQPProject:
    name: str


@dataclass
class IQPGroup:
    name: str
    projects: Dict[str, IQPProject]


@dataclass
class IQPHub:
    name: str
    groups: Dict[str, IQPGroup]


class QuantumUserProxy(get_user_model()):
    instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"

    class Meta:
        proxy = True

    def get_network(self, access_token: str) -> List[IQPHub]:
        if self.instances_url is None:
            return []

        return safe_request(
            request=lambda: requests.get(
                self.instances_url,
                headers={"Authorization": access_token},
                timeout=60,
            )
        )

    def get_instances_from_network(self, access_token: str) -> List[str]:
        instances = []

        network = self.get_network(access_token)
        for hub in network:
            groups = hub.groups.values()
            if not groups:
                instances.append(hub.name)
            else:
                for group in groups:
                    projects = group.projects.values()
                    if not projects:
                        instances.append(f"{hub.name}/{group.name}")
                    else:
                        for project in projects:
                            instances.append(f"{hub.name}/{group.name}/{project.name}")

        return instances
