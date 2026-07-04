#!/usr/bin/env bash
# Optional entrypoint that waits for Postgres, applies migrations (or bootstraps
# tables), then execs the given command. Used by the `api` service.
set -euo pipefail

echo "⏳ Waiting for Postgres at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}..."
until python -c "
import socket, os
s = socket.socket()
s.settimeout(2)
try:
    s.connect((os.getenv('POSTGRES_HOST','postgres'), int(os.getenv('POSTGRES_PORT','5432'))))
    print('ok')
except Exception:
    raise SystemExit(1)
"; do
  sleep 1
done
echo "✅ Postgres is up."

# Prefer real migrations if any exist, otherwise bootstrap tables for dev.
if ls migrations/versions/*.py >/dev/null 2>&1; then
  echo "▶️  Applying Alembic migrations..."
  alembic upgrade head
else
  echo "▶️  No migrations found — bootstrapping tables via metadata.create_all"
  python -m app.database.bootstrap
fi

exec "$@"
