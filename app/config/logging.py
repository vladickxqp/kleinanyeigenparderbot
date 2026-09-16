"""Centralised logging configuration using loguru.

Replaces the standard logging handlers so that libraries (aiogram, uvicorn,
SQLAlchemy, celery) all funnel through a single structured sink.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

from app.config.settings import settings

_LOG_DIR = Path("logs")


class InterceptHandler(logging.Handler):
    """Redirect standard-library logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """Configure loguru sinks and route stdlib logging through it."""
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        level=settings.log_level,
        format=log_format,
        backtrace=settings.debug,
        # diagnose=True dumps local variables into the traceback, which for an
        # exception raised near Bot(token=...) or the settings object means the
        # bot token and database password end up in the log file.
        diagnose=settings.debug and not settings.is_production,
        enqueue=True,
    )

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(
        _LOG_DIR / "app.log",
        level=settings.log_level,
        rotation="20 MB",
        retention="14 days",
        compression="zip",
        # Persisted logs never carry variable dumps: they would contain the
        # bot token or database password for any exception near the config.
        diagnose=False,
        enqueue=True,
    )
    logger.add(
        _LOG_DIR / "errors.log",
        level="ERROR",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        diagnose=False,
        enqueue=True,
    )

    # Route stdlib logging (used by third-party libs) into loguru.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "aiogram",
                  "sqlalchemy.engine", "celery", "httpx", "asyncio"):
        logging.getLogger(noisy).handlers = [InterceptHandler()]
        logging.getLogger(noisy).propagate = False

    logger.info(
        "Logging initialised (level=%s, env=%s)"
        % (settings.log_level, settings.environment)
    )
