#!/usr/bin/env bash
# Runs migrations before serving, so a fresh `docker compose up` has a schema.
set -euo pipefail

echo "Applying database migrations..."
alembic upgrade head

if [ "${SEED_ADMIN_EMAIL:-}" != "" ]; then
  python -m app.seed || echo "Seeding skipped."
fi

exec "$@"
