# API

`GET /health` and `POST /ask` served by FastAPI (`outage-matcher serve`).

## Sub-features
- typed request and response, citations as structured fields
- 503 until an agent is wired; 422 for invalid input, JSON errors with no stack traces

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
Proof: `/health` returns ok; `/ask` returns answer and citations (or a documented 503 if the agent is not wired in this checkout yet). `{"question": ""}` returns 422 JSON.

## Gotchas
- Check `git log` or the README to see whether `/ask` is wired to the real agent in this checkout.
- Kill only the PID in `.verify/serve.pid`.
