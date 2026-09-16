"""Celery application factory and beat schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

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
    # Redis' default visibility timeout is one hour: a task killed by a
    # redeploy would stay invisible that long before another worker retried
    # it, so the pipeline appeared dead right after every restart.
    broker_transport_options={"visibility_timeout": 300},
    # A broadcast may legitimately run far longer than a scrape.
    task_annotations={
        "app.worker.tasks.send_broadcast": {
            "time_limit": 3600,
            "soft_time_limit": 3300,
        },
    },
    # Paying customers are promised faster processing, so their searches get
    # their own queue instead of queuing behind everyone else's.
    task_default_queue="celery",
    task_queues=(
        Queue("express", Exchange("express"), routing_key="express"),
        Queue("priority", Exchange("priority"), routing_key="priority"),
        Queue("celery", Exchange("celery"), routing_key="celery"),
    ),
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
    "check-expired-subscriptions": {
        "task": "app.worker.tasks.check_expired_subscriptions",
        # Every 30 min instead of nightly: a lapsed subscription otherwise kept
        # full access for up to a day, and a skipped crontab run for two.
        "schedule": 1800.0,
    },
    "watchdog": {
        "task": "app.worker.tasks.watchdog",
        "schedule": 60.0,  # notice a stalled pipeline within minutes
    },
    "flush-unnotified": {
        "task": "app.worker.tasks.flush_unnotified",
        "schedule": 300.0,  # rescue listings whose delivery was interrupted
    },
    "weekly-recap": {
        "task": "app.worker.tasks.send_weekly_recaps",
        "schedule": crontab(day_of_week="sun", hour=18, minute=0),
    },
    "win-back": {
        "task": "app.worker.tasks.send_winbacks",
        "schedule": crontab(hour=17, minute=30),  # daily, after the expiry sweep
    },
    "dispatch-broadcasts": {
        "task": "app.worker.tasks.dispatch_broadcasts",
        "schedule": 15.0,  # pick up immediate + due scheduled broadcasts
    },
    "purge-old-data": {
        "task": "app.worker.tasks.purge_old_data",
        # Nightly and off-peak: deleting competes with the live pipeline for
        # the same tables, and nobody hunts deals at 03:30.
        "schedule": crontab(hour=3, minute=30),
    },
}
