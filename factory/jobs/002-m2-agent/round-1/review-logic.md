VERDICT: CHANGES

Reviewed at HEAD 8d9a30b (matches commands.md: 129 passed, ruff check and format clean). Scope: `git diff main...HEAD`.

Checked and fine:
- Graph termination: `route` caps at `max_retries`, `rewrite` always increments, and every branch reaches `answer`. The recursion limit (8 + 3*(max+1)) is above the worst-case 3*max+3 node visits. `max_retries=0` never rewrites.
- Tool-use contract: the assistant turn echoes the tool_use blocks. One user message then carries all tool_result blocks with matching `tool_use_id`, first in the content. Forced `tool_choice` is used only for single-tool structured calls. The loop is bounded by `MAX_TOOL_TURNS`, and the last turn's calls are still executed.
- `run_tool` handles unknown tool, non-dict args, bad or missing args, and any handler exception, and ends the transaction either way.
- Citations are validated against retrieved doc ids, and title/url/section come from the index. An answer with no valid citation degrades to no match. Empty or irrelevant retrieval gives the no-match answer without an answer LLM call.
- Search edge cases: empty index returns `[]`, k above the corpus size is fine, and an unknown embedding model raises `ValueError` in `search()`, which the tool returns as `tool_failed`.
- Tests are offline with fakes.

Findings:

1. src/outage_matcher/agent/graph.py:196-230 and 291-294 (with src/outage_matcher/cli.py:92-114): infrastructure failure is reported as "No close match found in the indexed postmortems".
   - `run_tool` turns every backend exception (DB connection lost, embedding model failed to load or download, pgvector error) into a `tool_failed` result.
   - If every retrieval attempt fails this way, `retrieved` stays empty. After the retry passes, the agent prints the honest-sounding no-match answer and `ask` exits 0.
   - The user is told the index has no match when the search never ran. That is the opposite of failures surfacing as clear errors.
   - The failure is visible only in `events`, and only if `--transcript` is used.
   - Fix: in `retrieve`, track tool results whose error type is `tool_failed` (backend failure, not model-caused `invalid_arguments`, `unknown_tool` or `not_found`). When nothing was retrieved and at least one call failed this way, either raise a dedicated `RetrievalError` that `cmd_ask` reports as a one-line error with exit 1, or at minimum set a note on the answer and print it, for example "search failed: <message>; this is not a no-match result". Add a test where the fake `search` raises and assert the result is not a plain no-match.

2. src/outage_matcher/cli.py:80-86 (`_build_agent`): `anthropic.Anthropic(api_key=api_key)` sets no explicit timeout or retry policy.
   - The SDK default is a 10 minute timeout with 2 retries. One stuck call can hang the CLI for about 30 minutes, and a run makes 8 or more calls.
   - The repo's other network client sets an explicit timeout (`ingest/collect.py:312`, `timeout=20.0`).
   - Fix: pass an explicit `timeout` (for example `timeout=60.0`, `max_retries=2`), ideally configurable through `AgentConfig`. `APITimeoutError` is already caught by the `anthropic.APIError` handler in `cmd_ask`. Add a test asserting the client is built with the timeout.

Non-blocking, no action required:
- graph.py:112-115: `_block_dict` echoes any text block, including an empty one. The Messages API rejects empty text blocks in input. This is rare but would turn into a 400 on the next turn. Consider skipping blocks with empty text.
- The live-API step (3 real transcripts) is correctly reported as not done. The default model name and forced `tool_choice` remain unverified against the real API, as build.md says.
