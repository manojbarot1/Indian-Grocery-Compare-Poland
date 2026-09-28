#!/usr/bin/env bash
# Nightly catalogue refresh: pull every shop, then re-match.
#
# Brings the stack up first, because the timer fires whether or not anyone
# left the containers running. Everything here is idempotent.
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/ops/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/refresh-$(date +%Y-%m-%d).log"

exec >>"$LOG" 2>&1
echo "=============================================================="
echo "refresh started $(date --iso-8601=seconds)"

cd "$PROJECT_DIR" || { echo "FATAL: $PROJECT_DIR missing"; exit 1; }

docker compose up -d db api || { echo "FATAL: could not start containers"; exit 1; }

# Wait for the API rather than guessing: Postgres takes a moment on a cold boot.
for _ in $(seq 1 60); do
  curl -sf -m 5 -o /dev/null http://localhost:8090/health && break
  sleep 2
done
if ! curl -sf -m 5 -o /dev/null http://localhost:8090/health; then
  echo "FATAL: API did not come up"; exit 1
fi

before=$(docker compose exec -T api python -c "
from app.db import SessionLocal
from app.models import Offer
from sqlalchemy import select, func
with SessionLocal() as s: print(s.scalar(select(func.count(Offer.id))))" 2>/dev/null | tr -d '\r')

docker compose exec -T api python cli.py refresh
status=$?

after=$(docker compose exec -T api python -c "
from app.db import SessionLocal
from app.models import Offer, Product
from sqlalchemy import select, func
with SessionLocal() as s:
    print(s.scalar(select(func.count(Offer.id))), s.scalar(select(func.count(Product.id))))" 2>/dev/null | tr -d '\r')

echo "offers before: ${before:-?}   after: ${after:-?}"
echo "refresh finished $(date --iso-8601=seconds) exit=$status"

# Keep a fortnight of logs; the crawl output is verbose.
find "$LOG_DIR" -name 'refresh-*.log' -mtime +14 -delete 2>/dev/null

exit $status
