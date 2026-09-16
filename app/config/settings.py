"""Typed application settings loaded from environment / `.env`.

Everything the app needs to run is described here as a single, validated settings
object. Secrets are read from the environment and are never written to logs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """All runtime configuration, validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General ------------------------------------------------------------
    environment: Environment = "development"
    debug: bool = True
    tz: str = "Europe/Berlin"
    log_level: str = "INFO"

    # --- Telegram -----------------------------------------------------------
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    bot_admin_ids: str = Field(default="", alias="BOT_ADMIN_IDS")
    bot_use_webhook: bool = Field(default=False, alias="BOT_USE_WEBHOOK")
    bot_webhook_base_url: str = Field(default="", alias="BOT_WEBHOOK_BASE_URL")
    bot_webhook_path: str = Field(default="/webhook", alias="BOT_WEBHOOK_PATH")
    bot_webhook_secret: str = Field(default="", alias="BOT_WEBHOOK_SECRET")

    # --- PostgreSQL ---------------------------------------------------------
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "parserbot"
    postgres_password: str = "change_me_postgres"
    postgres_db: str = "parserbot"

    # --- Redis --------------------------------------------------------------
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    # --- Celery -------------------------------------------------------------
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # --- API / security -----------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    jwt_secret_key: str = "change_me_generate_a_long_random_secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 14
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Scraping -----------------------------------------------------------
    scraper_default_interval_seconds: int = 300
    scraper_request_timeout: int = 25
    scraper_max_concurrency: int = 4
    scraper_min_delay_seconds: float = 2.0
    scraper_max_retries: int = 3
    scraper_proxies: str = ""
    playwright_headless: bool = True

    # --- AI -----------------------------------------------------------------
    ai_enabled: bool = False
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"

    # --- Monitoring ---------------------------------------------------------
    prometheus_enabled: bool = True
    #: External dead-man's switch (e.g. healthchecks.io). The worker pings it
    #: regularly; when the machine dies the ping stops and THAT service alerts.
    healthcheck_ping_url: str = ""
    #: Alert when no search was dispatched for this many seconds.
    watchdog_max_dispatch_age: int = 600
    #: Alert when the Celery queue holds more than this many tasks.
    watchdog_max_queue_depth: int = 100
    #: Alert when free disk space drops below this percentage.
    watchdog_min_disk_free_percent: float = 10.0

    # --- Premium / tier limits (all configurable, never hardcode) -----------
    premium_enabled: bool = True
    #: Monthly price in Telegram Stars (~250 XTR ≈ 4.99 €).
    premium_price_stars: int = 250
    #: Display price used in texts and revenue estimates.
    premium_price_eur: float = 4.99
    #: Days granted per successful (renewal) payment.
    premium_period_days: int = 31
    #: Rule quotas per tier.
    free_max_rules: int = 3
    pro_max_rules: int = 25
    unlimited_max_rules: int = 1_000_000
    #: Minimum allowed check interval per tier (seconds).
    free_min_interval_seconds: int = 600
    paid_min_interval_seconds: int = 60
    #: Free trial (activatable exactly once per user).
    trial_enabled: bool = True
    trial_days: int = 7
    #: Referral programme: free premium days for the inviter per first purchase.
    referral_enabled: bool = True
    referral_reward_days: int = 7

    # --- Resale / negotiation (all configurable) ----------------------------
    #: Marketplace fees deducted in the net-profit estimate (percent).
    resale_fee_percent: float = 13.0
    #: Flat shipping/handling cost deducted in the net-profit estimate (EUR).
    resale_shipping_eur: float = 5.90
    #: Default discount the negotiation assistant suggests (percent).
    nego_discount_percent: float = 12.0
    #: Photo evaluation is a premium perk by default (admins always allowed).
    photo_ai_premium_only: bool = True

    # --- Telegram Mini App ----------------------------------------------------
    #: Public HTTPS URL of the Mini App (e.g. https://deals.example.com/app).
    #: Empty = Mini App buttons are hidden; the bot works exactly as before.
    webapp_url: str = ""

    # --- Validators ---------------------------------------------------------
    @field_validator("bot_token")
    @classmethod
    def _warn_on_placeholder_token(cls, v: str) -> str:
        # We do not raise here so that non-bot components (api/worker) can boot
        # without a token; the bot entrypoint validates presence explicitly.
        return v.strip()

    #: Values that must never survive into a reachable deployment.
    PLACEHOLDER_SECRETS: ClassVar[frozenset[str]] = frozenset(
        {
            "change_me_generate_a_long_random_secret",
            "change_me_postgres",
            "change_me",
            "secret",
            "password",
        }
    )

    def insecure_secrets(self) -> list[str]:
        """Names of secrets still set to a placeholder or far too short.

        A default JWT secret is not a cosmetic issue: the value is public in
        this repository, so anyone could mint an admin token for the panel.
        """
        problems: list[str] = []
        if (
            self.jwt_secret_key in self.PLACEHOLDER_SECRETS
            or len(self.jwt_secret_key) < 32
        ):
            problems.append("JWT_SECRET_KEY")
        if self.postgres_password in self.PLACEHOLDER_SECRETS:
            problems.append("POSTGRES_PASSWORD")
        return problems

    def require_secure_secrets(self) -> None:
        """Abort startup when a placeholder secret would go live.

        Only enforced outside development so local experiments stay friction
        free, while a production container refuses to boot half-secured.
        """
        problems = self.insecure_secrets()
        if problems and self.is_production:
            raise RuntimeError(
                "Refusing to start: "
                + ", ".join(problems)
                + " still use(s) an insecure default. Generate real values, "
                "e.g. `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`."
            )
        if problems:
            from loguru import logger

            logger.warning(
                "⚠️ Insecure default secret(s): {}. Fine locally, never in production.",
                ", ".join(problems),
            )

    # --- Derived / computed -------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def admin_ids(self) -> list[int]:
        return [int(x) for x in self.bot_admin_ids.replace(" ", "").split(",") if x]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def proxy_list(self) -> list[str]:
        return [p.strip() for p in self.scraper_proxies.split(",") if p.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN (asyncpg driver)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Sync SQLAlchemy DSN (psycopg2) — used by Alembic."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg2",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return str(
            RedisDsn.build(
                scheme="redis",
                host=self.redis_host,
                port=self.redis_port,
                path=str(self.redis_db),
            )
        ).replace("redis://", f"redis://{auth}")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Module-level convenience singleton.
settings: Settings = get_settings()
