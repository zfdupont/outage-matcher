---
name: verify-outage-matcher
description: Launch and drive Outage Matcher (RAG agent over public postmortems; CLI plus FastAPI) against an isolated Postgres/pgvector instance, and capture proof that search, ask and the API work. Use when asked to verify, smoke test or demo the app, or to confirm a change works end to end.
---

# Verify Outage Matcher

Surfaces: a CLI (`uv run outage-matcher search|ask|ingest|serve`) and an HTTP API (`GET /health`, `POST /ask`). Everything depends on a Postgres/pgvector index of 235 postmortems (4482 chunks). Work from the repo root.

## Launch

```bash
.claude/skills/verify-outage-matcher/scripts/launch.sh
```

Starts an isolated compose project `outage-matcher-verify` (db on host port 55433, throwaway credentials generated into `.verify/env`, never touching the dev db on 5432), waits for the healthcheck, then loads the index:

- fast path: restores `~/outage-matcher-backup/index.sql` (a pg_dump of the real index, about 45 MB, takes seconds);
- fallback if that file is missing: `uv run outage-matcher ingest` (fetches about 235 pages at 1 to 2 s each, about 10 minutes, then embeds locally; pages may have changed, so counts and results can differ from the README).

Ready means: `doctor.sh` prints `READY` (db up AND 235 postmortems AND 4482 chunks present). A healthy container alone is not ready.

Every later command needs the isolated settings: `set -a; . .verify/env; set +a` (exports `DATABASE_URL`). The API key comes from the repo's `.env` (`ANTHROPIC_API_KEY`, must be a real workspace-scoped key; check with a 200 from `GET https://api.anthropic.com/v1/models` if `ask` returns 401 or 400).

## Doctor

```bash
.claude/skills/verify-outage-matcher/scripts/doctor.sh
```

Read-only. Reports: compose db container state, row counts, whether `ANTHROPIC_API_KEY` is set and not a placeholder, and whether something already owns port 55433 that is not ours. Run first whenever anything looks off.

## Drive

Free, no API key (embeddings are local):

```bash
set -a; . .verify/env; set +a
uv run outage-matcher search "database failover caused split brain" --k 5
uv run outage-matcher search "TLS certificate expired" --model bge --k 3 --system-type <label>
```

Expect ranked hits printed as `N. <title> [<section_type>] score=<x>` followed by a URL line, once per embedding model (bge and minilm) unless `--model` is given.

Uses the Anthropic API (about 10 to 20k tokens, a few cents):

```bash
uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" --transcript .verify/evidence/ask-lb.md
```

Expect: a likely cause, a suggested fix, citations that name real indexed postmortems with URLs, and a token usage line; the transcript file lists each tool call. An honest "no close match" abstention is valid output for a vague query, so use a specific incident description. Exit code 1 with one `error:` line means a backend or API failure, not a no-match.

API (after the agent is wired into the API, see `features/api.md`):

```bash
uv run outage-matcher serve --port 58000 &   # record the PID, kill only that PID
curl -s localhost:58000/health
curl -s -X POST localhost:58000/ask -H 'content-type: application/json' -d '{"question": "..."}'
```

More journeys are in `features/README.md`.

## Evidence

Write proofs to `.verify/evidence/` (git-ignored, survives cleanup). For each feature keep: the exact command, its stdout/stderr, and its exit code (`cmd 2>&1 | tee .verify/evidence/<name>.txt; echo "exit=${PIPESTATUS[0]}"`). Proof standards:

- Drive the real CLI or HTTP path, never import internals or fake the agent.
- For `ask`, capture the transcript and confirm every cited doc id exists: `psql` count in `postmortems` for each cited id.
- Retrieval proof is the ranked list plus checking at least one hit's URL appears in `data/manifest.jsonl`.
- Do not claim quality numbers from a smoke test; the measured numbers live in `evals/results/summary.md`.

## Cleanup

```bash
.claude/skills/verify-outage-matcher/scripts/teardown.sh
```

Stops and removes only the `outage-matcher-verify` compose project and its volume, and deletes `.verify/env`. It never touches other containers (the dev db on 5432, `m4-db-1`) and never deletes `.verify/evidence/`. Kill any `serve` process you started by PID.

## Helpers

- `scripts/launch.sh`: start isolated db, load index. Prints `.verify/env` path.
- `scripts/doctor.sh`: read-only readiness report, prints `READY` or what is missing.
- `scripts/teardown.sh`: remove the isolated project.

## Isolation

The project name, port 55433 and `.verify/` are verification-only, so it can run next to the dev db and other worktrees. Two simultaneous verify runs from different checkouts would collide on the project name and port; if `doctor.sh` says the port is owned by another project, stop and do not drive it.
