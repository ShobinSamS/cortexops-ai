from celery import Celery
from app.core.config import get_settings
from app.core.telemetry import configure_telemetry
configure_telemetry("cortexops-worker")

celery = Celery("cortexops", broker=get_settings().redis_url, backend=get_settings().redis_url, include=["app.workers.tasks"])
celery.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC", enable_utc=True,
                   task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
                   task_time_limit=1500, task_soft_time_limit=1440, result_expires=3600, broker_connection_retry_on_startup=True)
celery.conf.task_default_queue = get_settings().celery_queue
