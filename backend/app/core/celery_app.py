from celery import Celery
from app.core.config import get_settings
settings = get_settings()
celery_app = Celery("repopilot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"],
    task_track_started=True, task_time_limit=1800, task_soft_time_limit=1500,
    worker_prefetch_multiplier=1, task_acks_late=True)
celery_app.autodiscover_tasks(["app"])
