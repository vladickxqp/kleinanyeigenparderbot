# 🛒 Kleinanzeigen Parser Bot

An extensible, production-oriented **Telegram bot** that continuously hunts for the
best deals across many online marketplaces (Kleinanzeigen and AutoScout24, and —
via pluggable parsers — eBay, Idealo, and more). It parses listings, analyses prices,
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
  radius, category — plus mileage and year of registration for cars, asked of
  AutoScout24 server-side and re-checked locally. Every filter that depends on a
  value the ad may not state keeps the ad when it is unknown: a markup change must
  not empty a paid rule while the health checks stay green.
- **A rule from one sentence**: *"Tesla Model 3 unter 25.000 €, 100 km um Worms, keine
  Unfallwagen"* becomes a finished proposal to confirm — the eight-question wizard is
  still one tap away. Deterministic German parsing first (`app/services/rule_nlp.py`,
  works with `AI_ENABLED=false`); the optional model pass may only fill fields the
  rules could not, never overwrite one they did, and every value it returns is
  re-validated through the same coercers. Switch: `NL_RULES_ENABLED`.
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
# 2) generate real secrets — the app refuses to start in production otherwise:
#    python -c "import secrets;print(secrets.token_urlsafe(48))"   -> JWT_SECRET_KEY
#    python -c "import secrets;print(secrets.token_urlsafe(24))"   -> POSTGRES_PASSWORD
# 3) (optional) enable the admin panel login — see "Admin panel" below
docker compose up -d --build
docker compose logs -f bot
```

Services after `up`:

| Service    | URL / Port                     | Purpose                        |
|------------|--------------------------------|--------------------------------|
| Bot        | (Telegram)                     | the Telegram bot itself        |
| API        | http://localhost:8001/docs     | admin backend + Swagger        |
| Admin panel| http://localhost:8080          | React dashboard (nginx)        |
| Readiness  | http://localhost:8001/health/ready | DB, cache and pipeline state |
| Metrics    | http://localhost:8001/metrics  | Prometheus metrics             |

PostgreSQL and Redis are published on `127.0.0.1` only, so nothing on the
local network can reach them.

### Schema, backups and monitoring

The schema belongs to Alembic. A one-shot `migrate` service runs
`alembic upgrade head` before anything else starts, and every other service
waits for it. A database created by the older `create_all` bootstrap is adopted
by the baseline revision, so upgrading needs no manual step.

The `backup` service writes a compressed dump into `./backups` once a day and
deletes dumps older than `BACKUP_KEEP_DAYS`. Restore one with:

```bash
gunzip -c backups/parserbot-YYYYMMDD-HHMM.sql.gz | docker compose exec -T postgres psql -U parserbot -d parserbot
```

A watchdog task checks every minute whether searches are still being
dispatched, whether the queue is draining and whether the disk is filling up,
and alerts the admins in Telegram. Because it runs on the same machine that can
fail, it also pings an external dead-man's switch: set `HEALTHCHECK_PING_URL`
to a free healthchecks.io check and you get an alert when the laptop, Docker or
the database dies — the one failure the bot can never report itself.

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
npm run dev        # http://localhost:5173 (proxies /api to :8001)
npm run build      # production build into frontend/dist
```

Stack: React 18 + TypeScript + Vite + Tailwind + Recharts. Dark/light theme,
dashboard with charts, and pages for search rules, listings and parsers.

### Telegram Mini App (`/app`)

The same frontend also serves a **Telegram Mini App** at `/app`: deals,
searches (create, edit, pause, delete), flips & profit, premium status with the
exact charge dates and the full payment history — all inside Telegram, no
login. Authentication is Telegram's signed `initData` (verified server-side in
`app/api/webapp_auth.py`), so a user can only ever see their own data, and the
check interval is clamped to their tier on the server.

Telegram only loads Mini Apps from a **public HTTPS URL**. Cheapest setup
(free): a domain + Cloudflare Tunnel — nothing is exposed on your router.

1. Buy a domain and add it to Cloudflare (free plan).
2. Cloudflare Zero Trust → Networks → Tunnels → *Create a tunnel* → copy the
   token. Add a public hostname, e.g. `deals.example.com`, pointing to
   `http://frontend:80`.
3. In `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=<token>
   WEBAPP_URL=https://deals.example.com/app
   ```
4. Start with the tunnel profile and rebuild the bot:
   ```bash
   docker compose --profile tunnel up -d --build
   ```

The bot now shows **🌐 App öffnen** in the main menu and sets Telegram's
menu button automatically. With `WEBAPP_URL` empty, nothing changes.

---

## 📢 Broadcasts (admin)

`/broadcast` opens a wizard: send the announcement to the bot exactly as your
users should receive it (text, photo, video, document — formatting kept),
pick the audience (**all / free only / premium only**), optionally attach a
URL button, then choose *now* or a time (`2h`, `18:30`, `24.12. 18:00`).
You get a **preview of the real message** before anything is sent.

Delivery runs in the Celery worker, not in the bot: recipients are copied at
~20 msg/s, Telegram's flood control is honoured, users who blocked the bot are
counted and **deactivated automatically**, and the admin's status message is
edited with live progress and a final report (sent / blocked / failed).

- `/broadcast <text>` — one-liner to everyone, no wizard.
- `/broadcasts` — history with delivery stats; scheduled ones can be cancelled.
- The admin panel (`/admin`) has the same list under **📢 Broadcasts**.

---

## 💎 Plans, trials and privacy

Four levels, all as real Telegram Stars subscriptions. The ladder is
denominated in the resource that actually runs out: scrape requests per minute.
A single home connection carries roughly thirty per minute, so a plan that
promised everyone a one-minute interval would be selling the same capacity
several times over.

Every level therefore has a **base interval** for its searches plus a number of
**fast slots**: searches allowed to run at that level's fastest interval. The
top level does not buy a faster interval than the one below it, because below
one minute the marketplaces simply start blocking. It buys more fast searches,
a shorter base interval and its own worker queue.

| | Free | Starter | Profi | Händler |
|---|---|---|---|---|
| Searches | 3 | 10 | 30 | 100 |
| Base interval | 10 min | 5 min | 5 min | 3 min |
| Fast slots | – | 3 × 2 min | 10 × 1 min | 25 × 1 min |
| Cards per day | 10 | 100 | 500 | unlimited |
| Photo valuations | 1/month | 5/month | 30/month | unlimited |
| Quick searches | 3/day | 20/day | 100/day | unlimited |
| History kept | 14 days | 90 days | 1 year | 3 years |
| Price | – | 350 ⭐ | 750 ⭐ | 1500 ⭐ |

Every number in that table comes from settings; the bot renders it from
`app/services/entitlements.py`, so changing a price or a quota is a
configuration change. Usage is metered per user and shown in `/usage`. When a
cap is reached the bot says so and names what is being withheld — silence is
the worst failure mode for a deal bot.

The Händler plan only goes on sale once a proxy pool is configured
(`DEALER_REQUIRES_PROXIES`): at full speed one dealer needs more requests per
minute than a single address can carry.

Every grant lands in the payment ledger, including trials, coupons and referral
rewards, and a charge is booked exactly once even if Telegram redelivers the
update. A subscription records which level was bought, so a renewal can never
guess it. Quotas and fast slots are re-applied on every downgrade, expiry,
cancellation or refund, oldest searches first.

Users can see what is stored about them (`/privacy`), export it as JSON
(`/meinedaten`) and delete their account and data (`/loeschen`); the financial
ledger is kept but loses its personal link.

---

## ➕ Adding a new marketplace parser

1. Create `app/parsers/sites/<site>.py`.
2. Subclass `BaseParser`, set `site = SiteName.<SITE>` and implement `search()`.
3. Register the class — `@register_parser` for a verified parser, or the flagged
   form below while the extraction is still a guess.

**Register behind a flag until the parser has seen a live response.** A
`SearchRule` stores `sites=[]` by default and the registry resolves that to
*every* registered parser, so an unconditional `@register_parser` puts a new
parser in front of all existing users on the next deploy. Declare the class
undecorated and register it at the end of the module instead — `register_parser`
is a plain function, not only a decorator:

```python
if settings.<site>_enabled:      # default False in app/config/settings.py
    register_parser(MyParser)
```

**A JSON API site needs more than new selectors.** `app/parsers/sites/vinted.py`
is the reference for that case:

- **Own headers.** Override `_headers()` and call `super()._headers()` first, so
  the rotating user agent and language survive, then set a JSON `Accept` — the
  base one asks for HTML and an API typically answers that with an error page.
- **Own cookie handling.** `BaseParser.fetch` opens a fresh client per call and
  can therefore never carry a session. If the endpoint demands one, write a
  private `_fetch_json` that still `await self._throttle()`s (the politeness
  budget is shared and Redis-coordinated), uses `self._random_proxy()`, and runs
  the cookie-minting request and the API request through **one** client.
- **Only plain data on `self`.** Parser instances are process-wide singletons
  while the worker gives every task its own event loop, so cache a cookie dict
  and an expiry float — never a client, lock or any other asyncio primitive
  (see the note in `app/parsers/base.py`).
- **Separate "empty" from "blocked".** An empty result array is an honest
  "nothing matched"; a body without the expected array at all is a block or a
  schema change and must call `self.mark_suspected_block()`. Keep the 403 / 429
  / 503 marking `fetch` does; a 401 from an expired anonymous token deserves one
  silent refresh and retry first.
- **Keep extraction pure.** Put the mapping in a function over an
  already-decoded payload (no I/O) so tests can drive it from an inline fixture.
- **Never invent numbers.** Watch the decimal separator (a JSON API usually
  sends `12.50`, the German HTML pages send `12,50`), and let a filter the API
  cannot express be a no-op rather than one that silently empties the result.
- **`posted_at`.** Only add the site to `freshness.DATE_AWARE_SITES` once the
  timestamp semantics are confirmed against live data — a misread field there
  marks every listing stale and the site delivers nothing.

**A site whose search cannot be asked what you want.** `app/parsers/sites/autoscout24.py`
is the reference for the third case: the page ships its whole result list as JSON
inside `__NEXT_DATA__`, which is far steadier than CSS selectors — but the search
itself only speaks the site's own taxonomy.

- **Check that the site's free-text parameter does anything at all.** AutoScout24
  accepts `q=` and silently ignores it: "tesla model 3" and "zzzqqq" both answer
  HTTP 200 with the entire German inventory, ~870.000 cars. A parser that trusted
  it would flood every user with everything and look like it was working.
- **Resolve the rule into the site's own ids, and skip the request when you
  cannot.** A rule for "iPhone 15" names no car make, so it never leaves the
  house. Read the taxonomy from the payload the page already sends and cache it
  (`TAXONOMY_TTL_SECONDS`) — a make table baked into the source rots silently,
  and refetching it per search doubles the request cost that the plans are
  priced on.
- **Do not re-check locally what the site already filtered.** Once the search
  asked for BMW's "3er" group, every answer is one; requiring each ad to repeat
  "3er" in its title drops all of them, because dealers write the engine instead.
  Only the keywords the taxonomy did *not* consume are matched against the text.
- **Match the seller's spelling, not yours.** Dealers type "BMW 320 d" where the
  rule says "320d". The first live run of this parser returned 0 of 20 real hits
  for exactly that reason — see `close_variant_spacing`.
- **Say what the structured fields say, and nothing more.** The payload has no
  posting date, so `posted_at` stays `None` and the site stays out of
  `freshness.DATE_AWARE_SITES`; cars are collected rather than shipped, so
  `shipping_available` is `None` instead of `False`.

See `app/parsers/sites/kleinanzeigen.py` for a complete HTML reference
implementation, `app/parsers/sites/vinted.py` for the JSON API variant and
`app/parsers/sites/autoscout24.py` for the embedded-payload variant.

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
