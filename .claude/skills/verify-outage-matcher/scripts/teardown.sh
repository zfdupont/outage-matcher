#!/usr/bin/env bash
cd "$(git rev-parse --show-toplevel)" || exit 1
set -a; [ -f .verify/env ] && . .verify/env; set +a
docker compose -p outage-matcher-verify down -v >/dev/null 2>&1
rm -f .verify/env
echo "removed outage-matcher-verify (evidence kept in .verify/evidence)"
