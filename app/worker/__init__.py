"""Celery worker package: periodic scraping + notification dispatch."""

from app.worker.celery_app import celery_app

__all__ = ["celery_app"]
