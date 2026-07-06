"""Celery application factory and beat schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config.settings import settings

celery_app = Celery(
    "parserbot",
    broker=settings.effective_celery_broker,
    backend=settings.effective_celery_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.tz,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    task_time_limit=180,
    task_soft_time_limit=150,
    result_expires=3600,
)

# Beat schedule: a lightweight dispatcher decides which rules are due.
celery_app.conf.beat_schedule = {
    "dispatch-due-searches": {
        "task": "app.worker.tasks.dispatch_due_searches",
        "schedule": 20.0,  # seconds; per-rule interval is enforced inside the task
    },
    "flush-health-alerts": {
        "task": "app.worker.tasks.flush_health_alerts",
        "schedule": 60.0,  # deliver queued admin alerts once a minute
    },
    "daily-heartbeat": {
        "task": "app.worker.tasks.daily_heartbeat",
        "schedule": crontab(hour=20, minute=0),  # 20:00 local (settings.tz)
    },
    "flush-digests": {
        "task": "app.worker.tasks.flush_digests",
        "schedule": 600.0,  # check every 10 min whether quiet windows ended
    },
}
