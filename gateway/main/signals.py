from django.db.models.signals import post_save
from django.dispatch import receiver
from api.models import Job
from api.management.commands.schedule_queued_jobs import Command as Schedule
from api.management.commands.free_resources import Command as Free


@receiver(post_save, sender=Job)
def save_job(sender, instance, created, **kwargs):
    print("save_job")
    print(instance)
    print("Free")
    free = Free()
    free.handle()
    print("Schedule")
    schedule = Schedule()
    schedule.handle()
