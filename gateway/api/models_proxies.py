import requests

from django.conf import settings
from django.contrib.auth import get_user_model

from api.utils import safe_request


class QuantumUserProxy(get_user_model()):
    instances_url = f"{settings.IQP_QCON_API_BASE_URL}/network"

    class Meta:
        proxy = True

    def get_network(self, access_token: str):
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
        instances = []

        network = self.get_network(access_token)
        if network:
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
                                instances.append(f"{hub.get('name')}/{group.get('name')}/{project.get('name')}")

        return instances
