## Round 1
Commits:
- b8338f3 M4 step 1: wire the LangGraph agent into the API and serve command
- 951e238 M4 step 2: Langfuse callback and spans around nodes and tool calls, flush on exit
- 920e821 M4 step 3: eval workflow, local regression gate, fetch-raw (ESCALATE: CI workflow with secrets)
- 32de113 M4 step 4: README setup, architecture and commands, CLAUDE.md layout, tracing note, compose check

Changed:
- Step 1: `src/outage_matcher/api/agent.py` (new adapter, one DB connection per request), `api/app.py` (503 for RetrievalError and psycopg.OperationalError, 502 for anthropic.APIError, no detail leaked), `cli.py` (`serve_agent_factory`, `serve` uses it; `/ask` is 503 without a real key), `tests/test_api_agent.py`. The fake-agent tests in `tests/test_api.py` are unchanged.
- Step 2: `agent/graph.py` (callback from `get_tracer()` in the run config, `trace_span` on the four nodes as `node.<name>` and on each tool call as `tool.<name>`), `observability.py` (`flush()`, placeholder keys count as unset), `cli.py` (flush in `ask`), `tests/test_agent_tracing.py`, `tests/test_observability.py`.
- Step 3: `.github/workflows/eval.yml`, `src/outage_matcher/evals/gate.py`, `src/outage_matcher/ingest/collect.py` (`fetch_missing_pages`), `cli.py` (`fetch-raw`), `docs/ci-eval-gate.md`, `tests/test_evals_gate.py`, `tests/test_collect.py`, `tests/test_cli.py`.
- Step 4: `README.md` (setup, architecture diagram, commands, API, tracing and CI gate sections; the Results section is untouched, the diff has one hunk above it), `CLAUDE.md`, `docs/tracing.md`, `docs/compose-ask-example.md`.

Acceptance criteria:
- [x] Step 1: `POST /ask` calls the real agent, `serve` wires it, fake-agent tests kept (`test_ask_endpoint_runs_the_real_graph_with_fake_model_and_search`, `test_serve_factory_builds_the_agent_per_request_connection`, `test_serve_factory_is_none_without_a_real_key`, existing `tests/test_api.py`)
- [x] Step 2: callback on the graph, spans on every node and tool call, no-op when keys are unset, agent tested with tracing off (`test_agent_runs_with_tracing_disabled_and_touches_no_langfuse`, `test_tracer_is_attached_as_a_graph_callback_when_configured`, `test_each_node_and_tool_call_is_wrapped_in_a_span`, `test_agent_runs_with_the_real_langfuse_objects_when_keys_are_set`, `test_placeholder_or_blank_keys_do_not_enable_tracing`)
- [x] Step 3: `eval.yml` with pgvector service, `data/raw` cache keyed on the manifest hash with fetch only on a miss, version-equality check then tolerance comparison against `evals/baseline.json`, faithfulness job only on `workflow_dispatch` or when both secrets exist, secrets only via `secrets.*` in the steps that need them (`tests/test_evals_gate.py`, `test_fetch_missing_pages_fetches_only_what_is_absent`, `test_fetch_raw_*`). The workflow file is untested on GitHub (see Notes).
- [x] Step 4: README, CLAUDE.md, `docs/tracing.md`, `docs/ci-eval-gate.md`; `docker compose up --build` run with the real agent, `/health` and a real `/ask` through the container recorded in `docs/compose-ask-example.md`
- [x] Observable: `docker compose up --build` serves `GET /health` and `POST /ask` (checked). A trace per agent step in Langfuse is NOT verified live: no valid Langfuse keys were available (the keys in `.env` are the placeholders).

Commands: test (`uv run pytest -q`) -> 300 passed, 7 deselected (db marker); lint (`uv run ruff check .`) -> all checks passed; format (`uv run ruff format --check .`) -> 139 files already formatted

Notes:
- ESCALATE: `.github/workflows/eval.yml` handles secrets and has NOT been run on GitHub; Actions cannot run locally. The comparison it performs is `python -m outage_matcher.evals.gate` (`index` and `compare`), which is unit tested and was run against a real fresh index. YAML was only parsed with PyYAML. The `[ESCALATE]` marker is kept in the step 3 commit subject and in the workflow header comment. Please read it before merge: secrets appear only in the `keys` job (non-empty test, never printed) and the final faithfulness step; the DB service uses `POSTGRES_HOST_AUTH_METHOD: trust` so no password is stored. `permissions: contents: read`.
- Important finding for the owner: I ran the CI path by hand (`fetch-raw` of all 236 manifest pages, none failed, then `ingest --skip-collect` into a fresh db). The result has the same document and chunk counts and ids as the baseline index but a different index version (71c971dcffee vs the baseline's 34c67d0bba77). The only difference is one chunk of one CircleCI forum page where a view counter moved from 3721 to 3722. The recall@k and MRR of that run equal the baseline's (so the metrics gate would pass), but the strict version-equality rule the spec asks for makes the first CI run on a cache miss fail with the "refresh the baseline" message, and so will any source page that changes. Documented in `docs/ci-eval-gate.md`. I did not change the chunker or the version hash. Options for the owner: refresh the baseline and gold set on a fresh fetch, or relax the rule. Also, `data/raw` did not exist in the main checkout, so I fetched it myself; the fetch took about 5.5 minutes and the ingest about 17.7 minutes on this machine (while a docker build ran), which matters for the 45 minute job timeouts.
- `fetch-raw` is a new CLI command (not in the spec) because `ingest` without `--skip-collect` would re-crawl for new candidates and rewrite the committed manifest; `fetch-raw` fetches only the manifest's pages and never writes the manifest. It exits 0 on partial failures (warns) unless `--strict`, so the gate gives the explanation.
- Bug found by the compose run and fixed in the step 2 commit (via fixup): the `.env` Langfuse keys were the `your-key-here` placeholders, which enabled tracing and made the container log `Failed to export spans batch code: 401`. `tracing_enabled()` now treats empty and `your-` values as unset, like the Anthropic key check.
- Tests that moved: none deleted. `cli._api_key`, `_make_client` and `_build_agent` stay in `cli.py` (the evals import them and tests patch them); the serve factory reuses them.
- Branch history: while folding the placeholder fix into step 2 I ran `git rebase --autosquash main`, which also moved the branch onto the current `main` (it now includes `Open M4 job` and `Add verify-outage-matcher skill`, which are unrelated to my changes). Nothing was pushed.
- Docker check: separate compose project `-p m4`, db host port 55432, API port 18000, throwaway db password set only in my shell, torn down with `down -v` and the `m4-api` image removed. The main project's db container was not touched. The first `/ask` through the container returned a "no close match" answer; later ones returned cited answers (nondeterministic model, grader). Both are described honestly in `docs/compose-ask-example.md`. No secrets in docs.
- README Results section is byte-identical to before. New numbers in README: none. The corpus numbers in `docs/ci-eval-gate.md` and `docs/compose-ask-example.md` (236 pages, 235 documents, 4482 chunks, the two index versions) come from commands run in this job and are not recorded under `evals/results/`; they are in docs only, not in the README.
- Tracing: model calls go through the Anthropic SDK directly, so they are not separate generations; spans carry function arguments (incident text, excerpts). Node names show up twice in a real trace (handler run tree and explicit `node.*` spans). All stated in `docs/tracing.md`.
- Faithfulness job runs `needs: [retrieval, keys]` and rebuilds the index (a second ingest). On a PR with secrets it spends API credits on every push; the recorded run in the README Results gives the token scale. `workflow_dispatch` has a `limit` input.

## Round 2
Owner decision applied: a version change alone no longer fails the CI gate.
Commits:
- bf0236b M4 round 2: baseline records index document and chunk counts
- 9f46473 M4 round 2: gate fails on structural incompatibility, warns on a version change alone (ESCALATE: workflow)
- 5ee8192 M4 round 2: README and docs describe the new gate rule

Changed: `src/outage_matcher/evals/summary.py` and `evals/baseline.json` (new `index_documents` 235 and `index_chunks` 4482, copied from the recorded `bge-section.json`; `summary.md` is unchanged), `src/outage_matcher/evals/gate.py`, `tests/test_evals_gate.py`, `tests/test_evals_summary.py`, `.github/workflows/eval.yml`, `README.md`, `CLAUDE.md`, `docs/ci-eval-gate.md`, `docs/compose-ask-example.md`.

Acceptance criteria:
- [x] (1) Hard failure with the refresh message only when a gold held-out chunk id or relevant doc id is missing, or the document or chunk count is more than 2 percent from the baseline's (`test_missing_gold_chunk_id_is_a_hard_failure_naming_the_id`, `test_missing_relevant_doc_id_is_a_hard_failure_but_unconfirmed_duplicates_do_not_count`, `test_count_drift_beyond_two_percent_is_a_hard_failure_with_refresh_instructions`, `test_count_drift_up_to_two_percent_is_comparable`, `test_index_command_fails_on_a_missing_gold_chunk`, `test_index_command_fails_on_count_drift`)
- [x] (2) Otherwise recall@k and MRR compared with the tolerance (`test_drop_beyond_tolerance_fails_naming_the_metric`, `test_drop_within_tolerance_passes_and_exactly_at_the_floor_passes`, `test_version_differs_and_metrics_regress_fails_and_still_warns`)
- [x] (3) Version mismatch alone prints `WARNING` with old and new version and passes within tolerance (`test_version_differs_but_metrics_equal_passes_with_a_warning_naming_both_versions`, `test_index_command_warns_but_passes_on_another_version`, `test_compare_command_exit_codes_and_summary_file`); same version gives no warning (`test_same_version_and_metrics_pass_without_warning`)
- [x] eval.yml updated; README and `docs/ci-eval-gate.md` describe the new rule; `[ESCALATE]` header kept
Commands: test -> 311 passed, 7 deselected; lint -> all checks passed; format -> 139 files already formatted

Notes:
- Baseline had no counts, so I added `index_documents` and `index_chunks` to `baseline_document` and regenerated `evals/baseline.json` with the summary command (values from the recorded run; the old file's other fields are unchanged apart from the `rule` text, which now points to gate.py).
- `gate index` now takes `--gold` (default `evals/gold.jsonl`), asks the database which gold chunk ids and relevant doc ids exist, and checks counts. `gate compare` applies the count rule to the result file's counts; the id check needs the database, so it lives in `gate index` only. Unconfirmed near-duplicates do not count as relevant ids.
- Workflow change beyond the rule itself: `run_retrieval` and `run_faithfulness` refuse a gold set built on another index version, so both calls in eval.yml now pass `--allow-index-mismatch` (the `gate index` step runs first and has already checked ids and counts). Without this, the new warning-only rule would still have failed in `run_retrieval`. Step names are updated; still not run on GitHub.
- On GitHub Actions (`GITHUB_ACTIONS=true`) the warning is also emitted as a `::warning` annotation.
- Local re-run: I still had the fetched `data/raw` (no re-fetch), rebuilt a fresh index in a temporary compose project (`-p m4`, port 55432; ingest took 16.5 minutes), and ran the commands. `gate index` exit 0 with the WARNING (71c971dcffee against 34c67d0bba77, 235 documents, 4482 chunks); `run_retrieval --allow-index-mismatch` gave the same recall@1/3/5/10 and MRR as the baseline; `gate compare` printed the same WARNING, all five metrics `ok`, PASS, exit 0. The project was torn down with `down -v`. The result file was kept outside the repo.

## Round 3
Commits:
- 63b1a24 M4 round 3: gate index verifies gold chunk identity, clear error for an old baseline
- 16f6803 M4 round 3: fetch-raw --strict on every CI run, faithfulness job by dispatch only (ESCALATE: workflow)
- 5a846f4 M4 round 3: tolerance wording and rule path in baseline
- ac40bbe M4 round 3: verify skill describes the wired /ask
- bcfb478 M4 round 3: db connect timeout, AGENT_* forwarded to the api service and listed in CLAUDE.md

Changed: `src/outage_matcher/evals/gate.py`, `tests/test_evals_gate.py`, `.github/workflows/eval.yml`, `src/outage_matcher/cli.py`, `tests/test_cli.py`, `README.md`, `docs/ci-eval-gate.md`, `CLAUDE.md`, `src/outage_matcher/evals/summary.py`, `evals/baseline.json`, `.claude/skills/verify-outage-matcher/SKILL.md` and `features/api.md`, `src/outage_matcher/db.py`, `tests/test_db.py`, `docker-compose.yml`.

Review items addressed:
- (1) logic 1 and eval-rigor 1, gate identity: `gate index` now reads `id, postmortem_id, url, ord` for every gold chunk id (join on `postmortems`) and fails with the refresh message unless each chunk's document id equals the row's `doc_id`, its URL equals `doc_url` and its `ord` is in `held_out_ords`. Tests: `test_shifted_serial_ids_that_still_exist_are_a_hard_failure`, `test_each_identity_mismatch_alone_is_a_hard_failure` (doc id, URL, ord), `test_index_command_fails_on_shifted_ids_that_still_exist`. Missing keys: a baseline without `index_documents` or `index_chunks` (or `index_version`, `gold_sha256`) gives a one-line "Regenerate it with ...summary" error and exit 2 (`test_baseline_without_counts_is_a_clear_error_not_a_traceback`).
- (2) `fetch-raw --strict` already existed from round 1 (exit 1 if any manifest page is still not fetched; its help text now says so); the workflow runs it on every run in both jobs, with no cache-miss condition. logic 2 / api-contract 2 addressed. `keys` job: I removed it rather than adding a timeout, because with item (3) it has no purpose left (it only fed the PR trigger). In its place the faithfulness job begins with a "Require both API keys" step that fails fast before the slow ingest if either secret is empty (it tests non-empty only).
- (3) faithfulness job: `if: github.event_name == 'workflow_dispatch'` only, `needs: retrieval`. Workflow header, README and `docs/ci-eval-gate.md` updated with the reason (public repo, credits, PR-branch code would see the keys). `[ESCALATE]` header kept.
- (4) docs say 0.05 is about 1.7 gold queries (one flip passes, two fail) with a "why 0.05" section: set in M3 before any CI run existed. `summary.py` DEFAULT_TOLERANCE comment fixed. The `rule` text in `evals/baseline.json` now names `src/outage_matcher/evals/gate.py`, regenerated with `summary.py`. `git diff 5ee8192 HEAD -- evals/` shows only that line changed, so metrics, hashes, index version and counts are unchanged; `summary.md` unchanged.
- (5) verify skill: `features/api.md` and `SKILL.md` no longer say "check whether wired"; `/ask` is the real agent (503 without a real key, or backend down; 502 on model failure; 422), proof requires citations that exist in `postmortems`, startup warning and compose key forwarding noted.
- (6) `db.connect` passes `connect_timeout=10` (`CONNECT_TIMEOUT`; `test_connect_sets_a_connect_timeout`); `docker-compose.yml` forwards the four `AGENT_*` variables (empty means the defaults; `docker compose config` rendered them); CLAUDE.md Environment Variables lists them.

Commands: test -> 320 passed, 7 deselected; lint -> all checks passed; format -> 139 files already formatted

Notes:
- I did not touch `data/raw` and did not re-fetch. The compose `AGENT_*` change was checked with `docker compose config` only, not by rebuilding the container; the workflow is still untested on GitHub.
- The group 3 commit originally had a line over 100 characters in `summary.py` that I only noticed when running lint for group 6; I fixed it into the group 3 commit with a fixup and autosquash (this renumbered the later commits; the hashes above are final). Nothing was pushed.
- Because `fetch-raw --strict` runs on every CI run, any manifest page that cannot be fetched (robots, network) now fails the job; a rerun is the remedy.
