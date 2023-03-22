"""Api signals."""
import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ComputeResource


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def assign_compute_resource(
    sender, instance, created, **kwargs  # pylint: disable=unused-argument
):
    """Assign default compute resource on user creation."""
    if created:
        compute_resource = ComputeResource.objects.filter(
            title="Ray cluster default"
        ).first()
        if compute_resource is not None:
            compute_resource.users.add(instance)
            compute_resource.save()
        else:
            logging.warning(
                "ComputeResource was not found. "
                "No compute resources will be assigned to newly created user."
            )
