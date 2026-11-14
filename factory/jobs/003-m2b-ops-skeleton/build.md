## Round 1
Commits:
- 4cefa5f M2b step 1: FastAPI app with /ask and /health, serve command
- 9c2643d M2b step 2: Langfuse tracer and trace_span helper
- 8a4d638 M2b step 3: Dockerfile and compose api service
- 1458dd9 M2b step 4: CI workflow for lint, format and tests
Changed: pyproject.toml, uv.lock, src/outage_matcher/api/{__init__,models,app}.py, src/outage_matcher/cli.py, src/outage_matcher/observability.py, tests/test_api.py, tests/test_observability.py, Dockerfile, docker-compose.yml, .env.example, CLAUDE.md, .github/workflows/ci.yml
Steps:
- [x] Step 1 API: fastapi, uvicorn, langfuse added with uv add; AskRequest/Citation/AskResponse models; `Agent` Protocol and `create_app(agent_factory)` (factory called lazily, once); POST /ask, GET /health; JSON errors `{"error": {status, message, detail?}}` for 404/405/422/500 with no stack traces; missing agent (default factory returns None) gives 503; `outage-matcher serve [--host --port]` (tests: tests/test_api.py, 15 tests with TestClient)
- [x] Step 2 observability: `get_tracer()` returns the Langfuse langchain CallbackHandler when both keys are set else None; `trace_span` decorator (bare or named, sync and async), passthrough when tracing is off (tests/test_observability.py, 9 tests incl. real handler with tracing disabled and offline host)
- [x] Step 3 Docker: multi-stage uv Dockerfile, non-root uid 10001, HEALTHCHECK on /health via python urllib; compose `api` service with `${...}` env and depends_on db service_healthy. Verified: `docker compose -p m2b up --build -d` on host ports 55432/58000, api container reached `healthy`, `GET /health` returned 200 `{"status":"ok"}`, `POST /ask` returned 503, container runs as uid 10001; torn down with `down -v --rmi local`. The main checkout's db container was untouched.
- [x] Step 4 CI: .github/workflows/ci.yml runs `uv sync --frozen`, ruff check, ruff format --check, pytest on pull_request and push; no secrets.
Commands: test (`uv run pytest -q`) -> 78 passed, 4 deselected; lint (`uv run ruff check .`) -> All checks passed; format (`uv run ruff format --check .`) -> 48 files already formatted
Notes:
- Added `langchain-core` with `uv add` (in the step 1 commit with the other deps) because `langfuse.langchain.CallbackHandler` imports it; job 002 will likely bring it via langgraph, so expect an overlapping uv.lock/pyproject merge on that line.
- `.env.example` and CLAUDE.md gained `API_PORT` (host port for the api container); CLAUDE.md Commands lists `serve` and `docker compose up --build`.
- The copied .env has no POSTGRES_* values, so the container test passed throwaway POSTGRES_* values via the environment (not committed).
- `load_dotenv()` runs in `cmd_serve` so local `serve` picks up Langfuse keys; observability.py reads os.environ only.
- requirements.txt is `-e .`, so it stays in sync with pyproject automatically.
- No README numbers added.
