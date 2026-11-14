# Milestone job: build every step in order, one commit per step, no separate spec.

## Conventions

- One commit per step, brief messages, no Co-Authored-By lines, no emojis or em-dashes.
- Run `commands` (test, lint, format) after the last step; all must pass.
- Tests run offline: fake the Anthropic client and embedding models; mark anything needing network or Postgres with a pytest marker and skip it by default.
- Never commit secrets or `.env`. Read config from env vars listed in `.env.example`.
- Never invent or estimate metrics. Any number written into README.md must come from a recorded run whose output is committed under `evals/results/` (or `data/` for corpus stats).
- Use `uv add` for dependencies (it updates pyproject.toml and uv.lock); keep requirements.txt and requirements-dev.txt in sync with pyproject.toml.
- A step marked `[ESCALATE: why]` stops the milestone for the owner before merge.

## M2. Agent

**Goal:** a LangGraph agent that retrieves, grades, rewrites and retries, then answers with citations, using real Anthropic tool use.

**Steps:**
1. Add dependencies `langgraph` and `anthropic`. Config in `src/outage_matcher/config.py`: model name default `claude-haiku-5-5` (override by env `AGENT_MODEL`), max retries default 2.
2. Tools in `agent/tools.py` with JSON-schema definitions and implementations over the index: `search_incidents(query, k, system_type?)`, `get_postmortem(doc_id)`, `filter_by_system_type(system_type, query?)`. Tool errors return structured error results, never raise into the loop.
3. Graph in `agent/graph.py` with explicit state: `retrieve` node (the LLM chooses and calls tools via the Anthropic Messages API tool-use loop), `grade` node (LLM grades each retrieved chunk relevant or not, structured output), conditional edge to `rewrite` (LLM rewrites the query, increments the retry counter, hard cap) or `answer`, and `answer` node producing likely cause, suggested fix and citations referencing only retrieved doc ids. Empty or irrelevant retrieval after the cap yields an honest "no close match" answer.
4. Tests with a fake Anthropic client covering: tool call dispatch, malformed tool args, retry cap termination, citation validation (answer cannot cite an id that was not retrieved), no-match path.
5. CLI `outage-matcher ask "<incident description>"` printing the answer and citations; print token usage per run. Do a few real runs (requires `ANTHROPIC_API_KEY`; if it is not set in the environment or `.env`, stop with a clear note instead of failing) and save 3 example transcripts to `docs/examples/`.

**Observable:** `uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers"` returns a likely cause and fix citing real indexed postmortems.

