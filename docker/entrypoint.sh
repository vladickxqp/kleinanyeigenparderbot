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

# Schema is owned by Alembic. The baseline revision adopts a database that was
# created by the old create_all bootstrap, so upgrading an existing deployment
# needs no manual step.
if ls migrations/versions/*.py >/dev/null 2>&1; then
  echo "▶️  Applying Alembic migrations..."
  alembic upgrade head
  echo "✅ Schema is at: $(alembic current 2>/dev/null | tail -n1)"
else
  echo "⚠️  No migrations found — falling back to metadata.create_all"
  python -m app.database.bootstrap
fi

exec "$@"
