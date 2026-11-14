# API

`GET /health` and `POST /ask` served by FastAPI (`outage-matcher serve`).

## Sub-features
- typed request and response, citations as structured fields
- `/ask` runs the real agent; 503 without a real `ANTHROPIC_API_KEY` (missing or the `your-...` placeholder) or when the database or search backend is down, 502 when the model API call fails, 422 for invalid input; JSON errors, no stack traces

## How to get to it (user POV)
`uv run outage-matcher serve --port 58000`, or `docker compose up --build` (host port `API_PORT`).

## Driving it with curl
```bash
set -a; . .verify/env; set +a
uv run outage-matcher serve --port 58000 > .verify/serve.log 2>&1 & echo $! > .verify/serve.pid
until curl -sf localhost:58000/health; do sleep 1; done
curl -s -X POST localhost:58000/ask -H 'content-type: application/json' -d '{"question":"s3 style object store returned 503 after capacity change"}' | tee .verify/evidence/api-ask.json
kill "$(cat .verify/serve.pid)"
```
Proof: `/health` returns ok; `/ask` returns `answer`, `likely_cause`, `suggested_fix` and `citations` whose doc ids exist in `postmortems` (it uses the Anthropic API, a few cents per request, like `ask`). A 503 from `/ask` is a failed check when a real key is configured. `{"question": ""}` returns 422 JSON.

## Gotchas
- `serve` logs a warning at startup when the key is missing or still the placeholder; `/ask` then answers 503 until the process is restarted with a real key.
- In the container, `ANTHROPIC_API_KEY` must be in the environment: compose forwards it from `.env`, along with the `AGENT_*` and `LANGFUSE_*` variables.
- Kill only the PID in `.verify/serve.pid`.
