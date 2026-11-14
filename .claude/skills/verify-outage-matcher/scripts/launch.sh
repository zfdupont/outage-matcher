#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
P=outage-matcher-verify
PORT=55433
mkdir -p .verify/evidence
if [ ! -f .verify/env ]; then
  PW=$(openssl rand -hex 10)
  cat > .verify/env <<EOT
POSTGRES_USER=verify
POSTGRES_PASSWORD=$PW
POSTGRES_DB=verify
POSTGRES_PORT=$PORT
DATABASE_URL=postgresql://verify:$PW@localhost:$PORT/verify
EOT
fi
set -a; . .verify/env; set +a
docker compose -p "$P" up -d db >/dev/null
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$P-db-1" 2>/dev/null)" = healthy ] && break
  sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$P-db-1")" = healthy ] || { echo "db not healthy"; exit 1; }
N=$(docker exec "$P-db-1" psql -U verify -d verify -tAc "select to_regclass('public.postmortems') is not null and (select count(*) from postmortems) > 0" 2>/dev/null || echo f)
if [ "$N" != "t" ]; then
  BK="$HOME/outage-matcher-backup/index.sql"
  if [ -f "$BK" ]; then
    echo "restoring $BK"
    docker exec -i "$P-db-1" psql -q -U verify -d verify -v ON_ERROR_STOP=1 < "$BK" >/dev/null
  else
    echo "no backup at $BK; running full ingest (slow, network)"
    uv run outage-matcher ingest
  fi
fi
echo "env: $PWD/.verify/env"
