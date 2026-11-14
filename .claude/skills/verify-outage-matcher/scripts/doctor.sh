#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)" || exit 1
P=outage-matcher-verify; ok=1
[ -f .verify/env ] || { echo "missing .verify/env: run launch.sh"; exit 1; }
st=$(docker inspect -f '{{.State.Health.Status}}' "$P-db-1" 2>/dev/null || echo absent)
echo "db container: $st"; [ "$st" = healthy ] || ok=0
owner=$(docker ps --filter publish=55433 --format '{{.Names}}')
[ -z "$owner" ] || [ "$owner" = "$P-db-1" ] || { echo "port 55433 owned by $owner (not ours)"; ok=0; }
if [ "$st" = healthy ]; then
  pm=$(docker exec "$P-db-1" psql -U verify -d verify -tAc "select count(*) from postmortems" 2>/dev/null || echo 0)
  ch=$(docker exec "$P-db-1" psql -U verify -d verify -tAc "select count(*) from chunks" 2>/dev/null || echo 0)
  echo "postmortems=$pm chunks=$ch (expected 235 / 4482)"
  [ "$pm" = 235 ] && [ "$ch" = 4482 ] || ok=0
fi
k=$(awk -F= '$1=="ANTHROPIC_API_KEY"{print $2}' .env 2>/dev/null)
case "$k" in ""|your-*) echo "ANTHROPIC_API_KEY: missing or placeholder (search works, ask does not)";; *) echo "ANTHROPIC_API_KEY: set";; esac
[ $ok = 1 ] && echo READY || { echo NOT READY; exit 1; }
