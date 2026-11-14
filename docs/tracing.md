# Tracing with Langfuse

Tracing is optional. With no Langfuse keys the agent runs exactly as before: `get_tracer()`
returns `None`, the span decorators call the wrapped function directly, and nothing from
Langfuse is imported on the request path.

## Turn it on

Set these in `.env` (or the environment of the container; `docker-compose.yml` passes them to the
`api` service):

    LANGFUSE_PUBLIC_KEY=...
    LANGFUSE_SECRET_KEY=...
    LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL

Both keys must be set to real values; with only one, or with the `your-key-here` placeholders from
`.env.example`, tracing stays off. Then `uv run outage-matcher ask ...` or
`docker compose up --build` and a `POST /ask` produce one trace per question.

## What is recorded

`OutageAgent.ask` (`src/outage_matcher/agent/graph.py`) passes the Langfuse LangChain callback
handler from `observability.get_tracer()` to the LangGraph run as `config["callbacks"]`, and wraps
the following in `observability.trace_span` spans:

| Span | Wraps |
| --- | --- |
| `node.retrieve` | the retrieve node: the model's tool-use turns for one query |
| `tool.search_incidents`, `tool.get_postmortem`, `tool.filter_by_system_type` | each tool call made inside `node.retrieve` (nested in its node span) |
| `node.grade` | the relevance grading of the retrieved chunks |
| `node.rewrite` | a query rewrite (only when nothing relevant was found) |
| `node.answer` | the final answer with citations |

A question that needs one rewrite therefore shows `node.retrieve`, `node.grade`, `node.rewrite`,
`node.retrieve`, `node.grade`, `node.answer`, with a `tool.*` span under each retrieve. The
callback handler adds LangGraph's own run tree (the graph and its nodes) to the same trace, so the
node names appear twice: once from the handler (`retrieve`) and once from the explicit span
(`node.retrieve`).

The model calls go straight through the Anthropic SDK, not through LangChain, so they are not
recorded as separate generations; their time is inside the node spans. Spans carry the function
arguments and results (the incident text, retrieved excerpts, the answer), so only point
`LANGFUSE_HOST` at a Langfuse project you are comfortable storing those in.

`outage-matcher ask` flushes buffered traces before it exits. The API server relies on the Langfuse
client's background flush.

## What has been verified

The unit tests (`tests/test_agent_tracing.py`, `tests/test_observability.py`) cover the agent with
tracing off, the callback being attached, the span names and nesting through a recording fake, and
a run with the real Langfuse objects with export disabled (`LANGFUSE_TRACING_ENABLED=false`). A
trace arriving in a Langfuse project has not been verified: no Langfuse keys were available when
this was written.
