"""Model signal processing."""
import threading
import queue
from django.db.models.signals import post_save
from django.dispatch import receiver
from api.models import Job
from api.jobhandler import remove_resource, schedule_job

save_event = threading.Event()
job_update_queue = queue.SimpleQueue()


@receiver(post_save, sender=Job)
def save_job(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """procss save Job model entry event."""
    entry = {"id": instance.id, "status": instance.status}
    job_update_queue.put(entry)


def process_save_job():
    """procss save Job model."""
    while True:
        entry = job_update_queue.get()
        if entry["status"] in Job.TERMINAL_STATES:
            remove_resource(entry["id"])
        elif entry["status"] == Job.QUEUED:
            schedule_job(entry["id"])


def start_save_job_process():
    """start procss save Job model."""
    thread = threading.Thread(target=process_save_job, daemon=True)
    thread.start()
