"""Run a combined Celery worker + beat via ``python -m app.worker``.

For production you typically run worker and beat as separate processes; this
convenience entrypoint starts both (``--beat``) for local development.
"""

from __future__ import annotations

from app.config.logging import setup_logging
from app.worker.celery_app import celery_app


def main() -> None:
    setup_logging()
    celery_app.worker_main(
        argv=["worker", "--beat", "--loglevel=info", "--concurrency=4"]
    )


if __name__ == "__main__":
    main()
