"""FastAPI application factory for the admin backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app import __version__
from app.api.routers import (
    auth,
    health,
    listings,
    parsers,
    rules,
    settings as settings_router,
    stats,
)
from app.config.logging import setup_logging
from app.config.settings import settings
from app.database.session import dispose_engine

# Importing app.parsers triggers parser auto-discovery (registry population).
import app.parsers  # noqa: F401,E402


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    setup_logging()
    logger.info("API starting (env={}, v{})", settings.environment, __version__)
    yield
    await dispose_engine()
    logger.info("API stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Kleinanzeigen Parser Bot — Admin API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api_prefix = "/api"
    app.include_router(health.router, prefix=api_prefix)
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(stats.router, prefix=api_prefix)
    app.include_router(rules.router, prefix=api_prefix)
    app.include_router(listings.router, prefix=api_prefix)
    app.include_router(parsers.router, prefix=api_prefix)
    app.include_router(settings_router.router, prefix=api_prefix)

    if settings.prometheus_enabled:
        _mount_metrics(app)

    return app


def _mount_metrics(app: FastAPI) -> None:
    """Expose Prometheus metrics at /metrics if the client lib is available."""
    try:
        from prometheus_client import make_asgi_app

        app.mount("/metrics", make_asgi_app())
        logger.info("Prometheus metrics mounted at /metrics")
    except ImportError:  # pragma: no cover
        logger.warning("prometheus_client not installed; /metrics disabled")


app = create_app()
