## Conventions

- One commit per step, brief messages, no Co-Authored-By lines, no emojis or em-dashes.
- Run `commands` (test, lint, format) after the last step; all must pass.
- Tests run offline: fake the Anthropic client and embedding models; mark anything needing network or Postgres with a pytest marker and skip it by default.
- Never commit secrets or `.env`. Read config from env vars listed in `.env.example`.
- Never invent or estimate metrics. Any number written into README.md must come from a recorded run whose output is committed under `evals/results/` (or `data/` for corpus stats).
- Use `uv add` for dependencies (it updates pyproject.toml and uv.lock); keep requirements.txt and requirements-dev.txt in sync with pyproject.toml.
- A step marked `[ESCALATE: why]` stops the milestone for the owner before merge.

## M2b. Ops skeleton

**Goal:** the deployable shell around the agent, built in parallel with M2 on files M2 does not touch (api/, observability.py, Dockerfile, compose api service, CI lint/test workflow). Do not touch `src/outage_matcher/agent/`, `config.py` or ingest code.

**Steps:**
1. Add `fastapi`, `uvicorn` and `langfuse` with `uv add`. Define in `src/outage_matcher/api/models.py` the typed `AskRequest` and `AskResponse` (answer, likely_cause, suggested_fix, citations with doc id, title, url, section) and in `api/app.py` a `Protocol` `Agent` with `ask(question) -> AskResponse`; the app takes an agent factory so tests inject a fake. `POST /ask`, `GET /health`, errors as JSON with proper status codes and no stack traces. Until M4 wires the real agent, a missing agent returns 503. Tests with TestClient. CLI `outage-matcher serve`.
2. `src/outage_matcher/observability.py`: `get_tracer()` returns a Langfuse callback handler when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set, else None (no-op), with tests for both cases and a `trace_span` helper usable as a decorator.
3. `Dockerfile` multi-stage with uv, non-root user, `HEALTHCHECK` hitting `/health`; extend `docker-compose.yml` with an `api` service (env via `${...}` references, depends_on db healthy). Build the image and run the container with the db, confirm the healthcheck turns healthy and `GET /health` answers.
4. `.github/workflows/ci.yml`: lint, format check and tests on pull requests and pushes with uv; no secrets needed. (The eval gate comes in M4.)

**Observable:** `docker compose up --build` serves `GET /health`; `POST /ask` returns 503 until the agent is wired.

