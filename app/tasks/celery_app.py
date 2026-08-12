"""Celery app. Worker: celery -A app.tasks.celery_app worker --loglevel=info"""
from celery import Celery
from app.config import Config

celery_app = Celery("tdd_intelligence",
                    broker=Config.CELERY_BROKER_URL,
                    backend=Config.CELERY_RESULT_BACKEND,
                    include=["app.tasks.workflow_tasks"])

celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"],
    task_track_started=True, task_acks_late=True, worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
)
