# 🛒 Kleinanzeigen Parser Bot

An extensible, production-oriented **Telegram bot** that continuously hunts for the
best deals across many online marketplaces (Kleinanzeigen, and — via pluggable
parsers — eBay, Amazon, Idealo, and more). It parses listings, analyses prices,
filters by your rules, deduplicates results and pushes beautifully formatted deal
cards straight to Telegram.

> ⚠️ **Security note:** never commit real secrets. The Telegram bot token, database
> passwords and JWT secret all live in `.env` (git-ignored). If a token was ever
> committed, revoke it via [@BotFather](https://t.me/BotFather) → `/revoke`.

---

## ✨ Features (target scope)

- **Telegram bot** (aiogram 3): menu, inline & reply keyboards, FSM wizards, per-user
  search rules, favourites, history, statistics, blacklist/whitelist, multi-language.
- **Pluggable parsers**: every marketplace is a self-contained module registered in a
  central registry — add a new site without touching the core.
- **Flexible search rules**: keywords, exclude-words, price range, condition, location,
  radius, seller rating, category, brand, and arbitrary extra filters.
- **Price intelligence**: price history, average/min/max, discount %, anomaly detection
  ("possible seller mistake"), optional AI scoring (0–100) and resale/ROI mode.
- **Deduplication**: never send the same offer twice, even across different parsers.
- **Web admin panel** (React + Tailwind, later phase): dashboard, charts, logs, users,
  parsers, task queue, settings — everything configurable via the web.
- **Ops**: Docker Compose one-command startup, Celery workers, Redis cache/queue,
  Postgres, Prometheus + Grafana monitoring, structured logging (loguru).

---

## 🧱 Architecture

The project is a single Python package (`app/`) split into clear layers. This is
cleaner and more testable than scattering top-level folders, while still matching the
conceptual structure (bot / backend / parsers / …).

```
kleinanyeigenparderbot/
├── app/
│   ├── config/          # pydantic-settings config, logging setup
│   ├── database/        # SQLAlchemy async engine, models, repositories
│   │   └── models/
│   ├── parsers/         # BaseParser + registry + one module per site
│   │   └── sites/
│   ├── services/        # business logic: deal analysis, dedup, price stats
│   ├── bot/             # aiogram: handlers, keyboards, states, middlewares
│   │   ├── handlers/
│   │   ├── keyboards/
│   │   ├── states/
│   │   └── middlewares/
│   ├── worker/          # Celery app + periodic scraping tasks
│   └── api/             # FastAPI backend for the admin panel
│       └── routers/
├── migrations/          # Alembic migrations
├── docker/              # Dockerfiles
├── tests/
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

### Data flow

```
User → Telegram → Bot (FSM) → creates SearchRule in Postgres
                                         │
Celery Beat ── every N seconds ──────────┘
     │
     ▼
Worker picks due rules → ParserRegistry runs matching site parsers
     │
     ▼
Raw listings → dedup + price analysis + deal scoring
     │
     ▼
New good deals → formatted card → sent to the user in Telegram
```

---

## 🚀 Quick start (Docker)

```bash
cp .env.example .env
# 1) put your @BotFather token into BOT_TOKEN
# 2) set POSTGRES_PASSWORD / JWT_SECRET_KEY
# 3) (optional) enable the admin panel login — see "Admin panel" below
docker compose up -d --build
docker compose logs -f bot
```

Services after `up`:

| Service    | URL / Port                     | Purpose                        |
|------------|--------------------------------|--------------------------------|
| Bot        | (Telegram)                     | the Telegram bot itself        |
| API        | http://localhost:8000/docs     | admin backend + Swagger        |
| Admin panel| http://localhost:8080          | React dashboard (nginx)        |
| Metrics    | http://localhost:8000/metrics  | Prometheus metrics             |

The `api` service auto-creates the database tables on first boot (or applies
Alembic migrations if any exist — see `docker/entrypoint.sh`).

### Admin panel login

The admin API bootstraps a single admin from environment variables. Generate a
password hash and add it to `.env` (or the `api`/`frontend` environment):

```bash
docker compose run --rm api python -c \
  "from app.api.security import hash_password; print(hash_password('YOUR_PASSWORD'))"
# then set in .env:
#   ADMIN_USERNAME=admin
#   ADMIN_PASSWORD_HASH=<the printed hash>
```

## 🧑‍💻 Local development (without Docker)

```bash
python3.13 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
playwright install chromium
cp .env.example .env      # fill in BOT_TOKEN and DB/redis pointing at localhost
alembic upgrade head
python -m app.bot         # start the Telegram bot
python -m app.worker      # (separate shell) start a Celery worker + beat
uvicorn app.api.main:app --reload   # (separate shell) start the admin API
```

### Admin panel (frontend)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (proxies /api to :8000)
npm run build      # production build into frontend/dist
```

Stack: React 18 + TypeScript + Vite + Tailwind + Recharts. Dark/light theme,
dashboard with charts, and pages for search rules, listings and parsers.

---

## ➕ Adding a new marketplace parser

1. Create `app/parsers/sites/<site>.py`.
2. Subclass `BaseParser`, set `site = SiteName.<SITE>` and implement `search()`.
3. Decorate the class with `@register_parser` — that's it, the scheduler will use it.

See `app/parsers/sites/kleinanzeigen.py` for a complete reference implementation.

---

## ⚙️ Configuration

All configuration is environment-based (see `.env.example` for the full list).
Secrets are read once at startup through `app/config/settings.py` and are never logged.

---

## 🧪 Tests

```bash
pytest
```

---

## 📄 License

MIT — private project, for personal use. Respect each marketplace's Terms of Service
and robots.txt; the scrapers use polite rate-limiting by default.
