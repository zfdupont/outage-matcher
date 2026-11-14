VERDICT: CHANGES

Scope: HEAD 5ee8192 matches commands.md (pytest 311 passed, ruff check and format clean, so no command failures). Layout, entry points, config and docs otherwise check out: new code is under src/outage_matcher/ in the modules CLAUDE.md names (api/agent.py, evals/gate.py, ingest/collect.py, observability.py); the new `fetch-raw` command is a subparser of the already-declared `outage-matcher` script and is listed in CLAUDE.md Commands and the README; `gate` is documented as `python -m`; no new dependencies; every env var read is in .env.example (GITHUB_ACTIONS is a CI-provided variable); CLAUDE.md Architecture and Commands match the final layout; README, docs/ci-eval-gate.md, docs/tracing.md and eval.yml agree on the gate rule and flags (`--allow-index-mismatch`, `--results-dir`, `--name`, `--out` all exist).

1. `.claude/skills/verify-outage-matcher/features/api.md:7,18,23` and `.claude/skills/verify-outage-matcher/SKILL.md` (the "API (after the agent is wired into the API, see features/api.md)" line, around line 45): the verify skill still describes the pre-M4 behavior, which this job changes.
   - api.md says "503 until an agent is wired", "(or a documented 503 if the agent is not wired in this checkout yet)", and "Check `git log` or the README to see whether `/ask` is wired to the real agent". `/ask` is now wired. It runs the real agent when `ANTHROPIC_API_KEY` is real, and answers 503 only when the key is missing or is the `your-...` placeholder. It is also 503 when the database or search backend is down, and 502 when the Anthropic call fails.
   - Fix api.md:
     - Sub-features line: "503 without a real `ANTHROPIC_API_KEY` or when the backend is down, 502 when the model API call fails, 422 for invalid input; JSON errors, no stack traces".
     - Proof line: `/ask` returns answer, likely_cause, suggested_fix and citations whose doc ids exist in `postmortems`; a 503 is a failed check if a real key is configured.
     - Delete the "Check git log" gotcha.
     - Add that `serve` logs a warning at startup when the key is missing.
     - Note that the container needs the key in the environment: compose forwards `ANTHROPIC_API_KEY` from `.env`.
   - Fix SKILL.md: drop "(after the agent is wired into the API...)" and say `/ask` runs the agent and needs the API key (a few cents per request, like `ask`).

Non-blocking notes (no action required for PASS):
- `docker-compose.yml` forwards only ANTHROPIC_API_KEY and the LANGFUSE_* variables to the `api` service. The README lists `AGENT_MODEL` and the other `AGENT_*` variables as optional overrides in `.env`, but they do not reach the container, since compose does not pass them and `.env` is dockerignored. Either forward them in compose or add "for `uv run` only" in the README.
- The CLAUDE.md Environment Variables section does not list the `AGENT_*` variables that .env.example has. This was already the case before M4.
