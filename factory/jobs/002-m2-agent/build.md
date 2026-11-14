## Round 1
Commits:
- f447ea3 M2 step 1: add langgraph, anthropic and agent config
- c7f9493 M2 step 2: agent tools over the index
- c896150 M2 step 3: LangGraph agent with grade, rewrite and answer
- 95f2ba8 M2 step 4: agent tests with a fake Anthropic client
- 0e9f149 M2 step 5: ask CLI with usage and transcripts

Changed: pyproject.toml, uv.lock (uv add langgraph anthropic only), .env.example, CLAUDE.md, README.md, src/outage_matcher/config.py, src/outage_matcher/search.py, src/outage_matcher/cli.py, src/outage_matcher/agent/{__init__,models,tools,graph,transcript}.py, docs/examples/README.md, tests/{fakes,test_config,test_agent_tools,test_agent_graph,test_cli}.py. Nothing under api/, observability.py, Dockerfile or CI was touched. requirements.txt is `-e .`, so it needs no change.

Steps:
- [x] Step 1: deps and config. `config.py` gives `AgentConfig(model="claude-haiku-5-5", max_retries=2)`, overridden by env `AGENT_MODEL` and `AGENT_MAX_RETRIES` (both added to `.env.example`). Tests: tests/test_config.py.
- [x] Step 2: tools. `agent/tools.py` has JSON-schema `TOOL_DEFINITIONS` and `search_incidents`, `get_postmortem`, `filter_by_system_type`. `run_tool` never raises: bad args, unknown tool, unknown system_type, not found and backend exceptions all come back as `{"error": {"type", "message"}}` with `is_error=True`, and the connection is committed or rolled back after each call. Doc ids are `postmortems.id`; `SearchHit` gained a trailing `postmortem_id` field (default 0, so existing callers are unaffected) and `search()` selects `p.id`. Tests: tests/test_agent_tools.py (offline fake connection) plus one `db`-marked test against the real index.
- [x] Step 3: graph. `agent/graph.py` `OutageAgent` with explicit `AgentState`: `retrieve` (Messages API tool-use loop, max 4 model turns), `grade` (forced `submit_grades` tool, malformed output counts as not relevant), conditional edge to `rewrite` (forced `submit_query`, retry counter plus one, hard cap `max_retries`) or `answer` (forced `submit_answer`). Citations are validated against everything retrieved; invalid ids are dropped with a note, title/url/section come from the index not the model, and an answer left with no valid citation degrades to no match. No relevant chunks after the cap returns the no-match answer without an answer LLM call. Token usage is summed across all calls.
- [x] Step 4: tests with a fake Anthropic client (tests/fakes.py, tests/test_agent_graph.py): `test_tool_call_dispatch_and_answer_with_citations`, `test_malformed_tool_args_are_returned_to_the_model_not_raised`, `test_retry_cap_terminates_with_no_match`, `test_zero_retries_never_rewrites`, `test_answer_cannot_cite_a_document_that_was_not_retrieved`, `test_answer_with_only_invalid_citations_degrades_to_no_match`, `test_empty_retrieval_is_an_honest_no_match`, and others (rewrite feeds next retrieval, malformed grade and rewrite, tool-turn cap).
- [x] Step 5 (CLI part): `outage-matcher ask "<incident>" [--transcript PATH]` prints likely cause, fix, citations and token usage (LLM calls, input tokens, output tokens, rewrites). With a missing or placeholder key it prints a clear note and exits 1 without touching the database; Anthropic API errors are one-line errors. Tests in tests/test_cli.py.
- [ ] Step 5 (real runs and 3 example transcripts): SKIPPED. `ANTHROPIC_API_KEY` in `.env` is still the `your-key-here` placeholder and is not set in the environment, so no real run was made and no transcripts were fabricated. `docs/examples/README.md` states this and gives the command to record them (`ask ... --transcript docs/examples/<name>.md`). The Observable (`ask "checkout latency spiked after a config push to our load balancers"`) is therefore unverified against the real API.

Acceptance criteria:
- [x] Tool call dispatch (test_tool_call_dispatch_and_answer_with_citations, test_search_incidents_dispatch_and_retrieved)
- [x] Malformed tool args (test_malformed_tool_args_are_returned_to_the_model_not_raised, test_malformed_search_args_return_error_result)
- [x] Retry cap termination (test_retry_cap_terminates_with_no_match)
- [x] Citation validation (test_answer_cannot_cite_a_document_that_was_not_retrieved)
- [x] No-match path (test_empty_retrieval_is_an_honest_no_match, test_ask_no_match_says_so)
- [ ] Three real example transcripts in docs/examples/ (blocked on a real API key)

Commands: test (`uv run pytest -q`) -> 105 passed, 5 deselected (db marker). lint (`uv run ruff check .`) -> all checks passed. format (`uv run ruff format --check .`) -> 53 files already formatted.

Notes:
- The running Postgres container's password differs from the DATABASE_URL in the main checkout `.env`, so DB-marked tests fail with auth errors unless DATABASE_URL is overridden. I ran them with a DATABASE_URL built from the container's own env (not written to any file): the new `db` tool test and the existing search `db` tests passed (3 passed). The index was not modified.
- The agent has only been exercised against fakes and the real tools/index, never the real Anthropic API. First real run may need tweaks (for example if the chosen model rejects a forced `tool_choice` or some schema keywords).
- The default model name `claude-haiku-5-5` comes from the spec and was not verified against the live API.
- Design choice to review: `get_postmortem` registers one `full_document` chunk (text capped at 6000 chars) as retrieved evidence, so it is graded and citable like search hits; `filter_by_system_type` without a query only lists documents and registers nothing.
- Commits carry no Co-Authored-By line, per the job instructions.

## Round 2
Commits:
- 06f5ac6 Fail ask on backend search failure instead of reporting no match
- a0a9158 Explicit Anthropic client timeout and retry count
- 05fc528 Skip empty text blocks when echoing, sort deps

Changed: src/outage_matcher/agent/{graph,models,tools}.py, src/outage_matcher/{config,cli}.py, .env.example, CLAUDE.md, pyproject.toml, tests/{test_agent_graph,test_cli,test_config}.py. The merged-in main (M2b) is untouched and still merged.

Review items addressed:
- Logic 1 (backend failure reported as no-match) -> `retrieve` collects `tool_failed` results (constant `BACKEND_ERROR` in tools.py, model mistakes such as invalid_arguments and not_found are excluded). If a retrieve pass found no chunks and had at least one backend failure, it raises the new `RetrievalError` ("search failed: <message>; this is not a no-match result") and the graph stops without retrying or grading. A failure the model recovers from within the same pass (a later successful search) is not an error. `RetrievalError` is a `RuntimeError`, so `main` prints a one-line `error: ...` and exits 1. Tests: test_backend_failure_raises_instead_of_reporting_no_match (search raises), test_backend_failure_after_an_empty_search_still_raises, test_backend_failure_recovered_within_the_pass_is_not_an_error, test_model_mistakes_are_not_backend_failures, test_ask_search_failure_is_a_one_line_error_not_a_no_match.
- Logic 2 (no client timeout or retry policy) -> `AgentConfig` gains `request_timeout` (default 60 s, env `AGENT_REQUEST_TIMEOUT`, min 1) and `api_max_retries` (default 2, env `AGENT_API_MAX_RETRIES`, min 0); both are in `.env.example` and CLAUDE.md. New `cli._make_client` builds `anthropic.Anthropic(api_key, timeout, max_retries)`; `_build_agent` now takes the client. Tests: test_client_is_built_with_explicit_timeout_and_retries (asserts client.timeout and max_retries), test_ask_builds_the_client_from_config, and config tests for defaults, env overrides and bad values.
- Logic non-blocking (empty text block echo) -> `_block_dict` replaced by `_echo_blocks`, which skips empty or whitespace-only text blocks. Tests: test_empty_text_blocks_are_not_echoed_back_to_the_api, test_non_empty_text_blocks_are_echoed.
- Maintainability nit 1 (redundant local `load_dotenv` in `cmd_serve`) -> removed (in commit a0a9158).
- Maintainability nit 2 (`anthropic` imported in both `cmd_ask` and `_build_agent`) -> `_build_agent` no longer imports it; `anthropic` is imported only in `cmd_ask` (for the error handler) and `_make_client`.
- Maintainability nit 3 (pyproject order) -> `langchain-core` now sorted before `langgraph`; `uv lock` reports no change to uv.lock.

Commands: test (`uv run pytest -q`) -> 142 passed, 5 deselected. lint (`uv run ruff check .`) -> all checks passed. format (`uv run ruff format --check .`) -> 71 files already formatted.

Notes: the real-API runs and transcripts remain undone (the key is still a placeholder), as in round 1. Commit messages have no attribution lines.
