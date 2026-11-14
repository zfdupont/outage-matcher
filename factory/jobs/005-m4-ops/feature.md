## Conventions

- One commit per step, brief messages, no Co-Authored-By lines, no emojis or em-dashes.
- Run `commands` (test, lint, format) after the last step; all must pass.
- Tests run offline: fake the Anthropic client and embedding models; mark anything needing network or Postgres with a pytest marker and skip it by default.
- Never commit secrets or `.env`. Read config from env vars listed in `.env.example`.
- Never invent or estimate metrics. Any number written into README.md must come from a recorded run whose output is committed under `evals/results/` (or `data/` for corpus stats).
- Use `uv add` for dependencies (it updates pyproject.toml and uv.lock); keep requirements.txt and requirements-dev.txt in sync with pyproject.toml.
- A step marked `[ESCALATE: why]` stops the milestone for the owner before merge.

## M4. Ops

**Goal:** wire everything together: real agent in the API, Langfuse tracing of each agent step, CI eval gate. Depends on M2, M2b and M3 being merged.

**Steps:**
1. Wire the LangGraph agent into the API factory (`POST /ask` calls the real agent) and the `serve` command; keep the fake-agent tests.
2. Langfuse tracing: use `observability.get_tracer()` as a callback on the graph and wrap each tool call and node in a span; tracing stays a no-op when keys are unset; test the agent with tracing disabled.
3. `.github/workflows/eval.yml`: on pull requests start a pgvector service container, run ingest from the manifest, run the retrieval eval and compare with `evals/baseline.json`, failing the job when recall@k or MRR drops beyond the tolerance. The LLM-judged faithfulness job runs only on `workflow_dispatch` or when the `ANTHROPIC_API_KEY` secret is present. Secrets come only from GitHub secrets. `[ESCALATE: CI workflow that handles secrets, owner should read it before merge]`
4. Update README (setup, text architecture diagram, commands, results section kept from M3), CLAUDE.md Architecture to match the final layout, and a short tracing note under `docs/`. Run `docker compose up --build` once more with the real agent and confirm `/health` and a `/ask` request (needs the API key).

**Observable:** `docker compose up --build` serves `POST /ask` and `GET /health`; Langfuse shows a trace per agent step when keys are configured.
