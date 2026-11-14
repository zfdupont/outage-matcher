## Round 1
Commits (branch factory/004-m3-evals, base main):
- f8c32ef M3 step 1: gold set builder (DeepSeek client, leak checks, dry run)
- dead3d0 M3 step 1: use deepseek-flash, configurable via DEEPSEEK_MODEL
- 5de8a19 M3 step 1: gold set of 34 queries generated with deepseek-flash
- b5efc86 M3 step 2: retrieval metrics and run_retrieval harness
- f1d4805 M3 step 3: reranker and neighbor chunking, embedding model and reranker runs
- eb40e43 M3 step 3: neighbor chunking run
- 1b85529 M3 step 4: faithfulness judge, held-out exclusion in agent tools
- 2d2dc30 M3 step 5: summary and baseline generator
- d8a8974 M3 step 6: README evals and results from summary.md, CLAUDE.md commands (also commits the generated evals/results/summary.md and evals/baseline.json)

Changed: src/outage_matcher/evals/ (new: corpus, deepseek, gold, build_gold, metrics, retrieval, chunking, rerank, run_retrieval, faithfulness, run_faithfulness, summary), evals/ (entry scripts, gold.jsonl, baseline.json, results/*.json, results/summary.md), src/outage_matcher/search.py (optional `exclude_chunk_ids`), src/outage_matcher/agent/{tools,models,graph}.py (hidden chunk ids in ToolContext; `AgentResult.evidence`), tests/test_evals_*.py plus additions to test_search, test_agent_tools, test_agent_graph, .env.example, .gitignore (evals/cache/), CLAUDE.md, README.md.

Steps:
- [x] Step 1 evals/build_gold.py: REAL RUN DONE. 34 queries in evals/gold.jsonl (target 40; only 35 documents have a clear root-cause section after excluding monthly GitHub availability digests, 1 was marked unusable by the model). Model deepseek-flash, temperature 0.2, 2026-11-13, index version 34c67d0bba77. DeepSeek usage: 70 calls, 94207 input tokens, 3385 output tokens. Held-out section = all root_cause chunks of the doc; ids, ords, heading stored. Test names: tests/test_evals_gold.py (leak checks, retry, near-dup parsing, build/round-trip), tests/test_evals_deepseek.py.
- [x] Step 2 metrics + run_retrieval: tests/test_evals_metrics.py (hand-checked recall@k, MRR), tests/test_evals_retrieval.py (exclusion, ranking, result file, --help); one `db` test against the real index.
- [x] Step 3 comparison + improvement: REAL RUNS DONE on the identical gold set. bge-section MRR 0.519 vs minilm-section 0.391, so baseline = bge section. Improvement = cross-encoder reranker Xenova/ms-marco-MiniLM-L-6-v2 over top 50: MRR 0.646, recall@1 0.588 (10 queries better, 5 worse). Extra configuration: neighbor chunking, MRR 0.515 (no gain). Result files in evals/results/. Tests: tests/test_evals_improvements.py (reranker head/tail reorder, held-out text not leaking through neighbor context, cache, config recorded).
- [x] Step 4 evals/run_faithfulness.py: CODE AND TESTS DONE, REAL RUN PENDING (see below). Tests: tests/test_evals_faithfulness.py, plus new tests for search/tool exclusion and AgentResult.evidence. The judge prompt was smoke-tested once against the live DeepSeek API on a handwritten answer (output parsed correctly; not recorded anywhere).
- [x] Step 5 summary + baseline: evals/results/summary.md and evals/baseline.json generated from the result files (tolerance 0.05 absolute, about 1.7 gold queries; stated in the file). Baseline run = bge-section (what the agent uses today). Tests: tests/test_evals_summary.py.
- [x] Step 6 README: Evals section, Results section (retrieval tables copied from summary.md), limitations (synthetic queries, n=34, same-set selection, deepseek-flash id). No faithfulness number is in the README.

Acceptance criteria:
- [x] AC1 gold set builder, held-out root cause, symptoms-only query, near-dups, model and date recorded (test_build_gold_records_doc_held_out_section_and_generation, test_leak_problems_flags_each_kind_of_leak; real file evals/gold.jsonl)
- [x] AC2 recall@1/3/5/10 and MRR with hand-checkable tests; run_retrieval writes config, date, index version, per-query ranks (test_recall_at_k_on_a_hand_checked_set, test_mrr_on_a_hand_checked_set, test_main_writes_a_result_file_with_config_index_and_per_query_ranks)
- [x] AC3 two embedding models compared, one improvement measured on the identical gold set, runs recorded (evals/results/*.json; check_comparable enforces identical gold sha256 and index version: test_runs_on_different_gold_sets_or_indexes_are_not_compared)
- [ ] AC4 faithfulness judge: implemented and tested offline, real run NOT done (Anthropic key rejected)
- [x] AC5 summary.md generated from result files, baseline.json with tolerance (test_main_writes_summary_and_baseline, test_baseline_document_states_the_tolerance_and_ties_to_gold_and_index); faithfulness section of summary appears once that run exists
- [x] AC6 README Results numbers copied from summary.md; synthetic limitation stated (the faithfulness paragraph states it has not run)
- [x] `uv run python -m outage_matcher.evals.run_retrieval --help` works (test_help_lists_the_options)

Commands: test (`uv run pytest -q`) -> 239 passed, 7 deselected (db tests; the 7 db tests also pass with `-m db` against the running container); lint (`uv run ruff check .`) -> all checks passed; format (`uv run ruff format --check .`) -> 104 files already formatted.

Notes:
- PENDING REAL RUNS (blocked): ANTHROPIC_API_KEY in .env is rejected by Anthropic. `GET https://api.anthropic.com/v1/models` with that key returns 401 invalid x-api-key, and `outage-matcher ask` returns the same 401 through the SDK (the shell also has ANTHROPIC_BASE_URL set; the direct call to api.anthropic.com failed the same way, so it is the key). Therefore not done: the live sanity check of `claude-haiku-5-5` and forced `tool_choice` (still unverified), the 3 example transcripts in docs/examples/, and the faithfulness run. Nothing was fabricated. After putting a valid key in /Users/zfdupont/outage-matcher/.env and copying it to the worktree .env, run (with DATABASE_URL overridden for the container):
  1. `uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" --transcript docs/examples/lb-config-push.md` (if the model name or tool_choice is rejected, set AGENT_MODEL to a working cheap model and record it here), then two more `ask ... --transcript docs/examples/<name>.md` with different incidents.
  2. `uv run python evals/run_faithfulness.py --dry-run` for the token estimate, then `uv run python evals/run_faithfulness.py` (prints actual agent and judge token usage; writes evals/results/faithfulness.json; `--limit 5` first for a cheap trial; 3 consecutive failures abort the run).
  3. `uv run python -m outage_matcher.evals.summary` (regenerates summary.md and baseline.json, adds the faithfulness section), then copy the faithfulness numbers from summary.md into the README Results section (replace the "Faithfulness has not been run yet" line and the last limitation) and update docs/examples/README.md.
- DeepSeek model change (per coordinator): `GET /models` lists only `deepseek-flash` (DeepSeek-V4.1-Flash) and `deepseek-v4-pro`; picked `deepseek-flash`. It is a reasoning model, so the client sends `"thinking": {"type": "disabled"}` (otherwise reasoning tokens eat max_tokens and temperature is ignored; temperature 0 for the judge is therefore meaningful). `DEEPSEEK_MODEL` env var added to .env.example and CLAUDE.md, default deepseek-flash. The model id is recorded in gold.jsonl (per row) and will be in the faithfulness result file. The retrieval result files record the gold generation block (model, temperature, date). The spec text still says deepseek-chat; milestones.md untouched as instructed.
- Gold quality caveats for the reviewer: some queries still carry hints (for example q020 and q032 mention symptoms close to the remediation); the automated filter only blocks 5-word runs from the root-cause text and 8-word runs from the document and source host names. Near-duplicates: the model suggested only 1 (q020 -> doc 2, Cloudflare Nov 18 2025 outage). It is left unconfirmed (the Code Orange post covers two incidents, so it is related, not clearly the same document); set `confirmed: true` in gold.jsonl by hand to count it, then rerun the runs (gold sha256 changes and summary refuses mixed gold versions).
- Retrieval evals use exact cosine over all chunk vectors in numpy (not the HNSW index), so held-out chunks can be excluded exactly; the agent path uses pgvector search with a new `exclude_chunk_ids` filter. Documented in result files (`config.search`) and README.
- The faithfulness judge sees the retrieved chunks of cited documents (`AgentResult.evidence`, a new defaulted field), 3000 chars per chunk, 15000 total. Abstentions (no match) and errors are counted separately and not scored.
- Baseline tolerance 0.05 is a stated policy choice, not a measurement.
- Neighbor chunking embeds all chunks once (about 35 minutes on this machine) and caches to evals/cache/ (git-ignored).
- Tests are offline; fakes for DeepSeek (httpx.MockTransport and scripted client), embedders and Anthropic; db-marked tests skipped by default.
- .env was copied into the worktree (git-ignored); no key was printed or committed.

## Round 2
Commits (branch factory/004-m3-evals):
- eea2fdc Round 2: declare numpy as a dependency
- d3b7b4b Round 2: judge retries invalid JSON, evidence keeps answered chunks first and skips only what does not fit
- 5c4a343 Round 2: drop unused DocRow.system_type
- 18a48f4 Round 2: summary refuses a faithfulness result from another gold set or index
- 28b5406 M3 step 4: faithfulness run, example transcripts, summary and README results (the real runs the coordinator asked for after the new key)

Changed: pyproject.toml, uv.lock (numpy>=2.5.4); src/outage_matcher/evals/{deepseek,faithfulness,corpus,summary,run_faithfulness}.py; src/outage_matcher/agent/{graph,models}.py; tests (test_evals_deepseek, test_evals_faithfulness, test_evals_summary, test_evals_gold/retrieval/improvements constructors, test_agent_graph); evals/results/{faithfulness.json,summary.md}; docs/examples/; README.md. evals/gold.jsonl, evals/baseline.json and the four retrieval result files are untouched (verified with git diff against d8a8974).

Review items addressed:
- Maintainability 1 (numpy undeclared) -> `uv add numpy`; pyproject.toml and uv.lock updated; requirements*.txt need no change (`-e .`).
- Logic 1 (evidence cap `break`, ordering) -> `cited_evidence` uses `continue`; `AgentResult.evidence` now lists the chunks shown to the answerer first (`relevant[:MAX_ANSWER_CHUNKS]`), then the rest retrieved. Tests: test_cited_evidence_skips_a_chunk_that_does_not_fit_but_keeps_later_small_ones, test_cited_evidence_keeps_the_order_of_the_result_so_seen_chunks_win_the_budget, test_evidence_lists_the_chunks_the_answerer_saw_before_the_rest.
- Logic 2 (judge retry on invalid JSON) -> new `InvalidReplyError(DeepSeekError)` raised by `chat_json` for non-JSON, non-object, wrong-shape replies (carries the call's token usage); `judge_answer` retries once on it (and on a bad verdict shape), counts the failed attempt's tokens, does not retry transport errors (already retried in the client), re-raises after the last attempt. Judge `max_tokens` raised 2000 -> 4000. Tests: test_judge_answer_retries_once_when_the_reply_is_not_json_or_cut_off, ..._gives_up_after_two_invalid_replies, ..._does_not_retry_transport_failures, test_reply_that_is_not_a_json_object_is_an_invalid_reply_that_keeps_its_usage, test_transport_failures_are_not_invalid_replies.
- Maintainability note (unused DocRow.system_type) -> removed from the dataclass, the query and the tests.
- Rigor note 1 (faithfulness vs retrieval consistency) -> `check_comparable` now includes faithfulness.json; a different gold sha256 or index version raises and `summary.main` exits 1 without writing. Test: test_a_faithfulness_result_from_another_gold_set_or_index_is_refused.

Real runs after the new key (all keys worked):
- Live check: `outage-matcher ask` accepted the default `claude-haiku-5-5` and the forced tool_choice; no model change needed. Transcripts recorded (real runs, 2026-11-13): docs/examples/lb-config-push.md (4 calls, 7116 in / 813 out tokens), expired-certificate.md (4 calls, 7132 / 873), db-failover-split-brain.md (5 calls, 12548 / 1023; ends in "no close match", kept as recorded, see below).
- Faithfulness: `run_faithfulness.py --dry-run` estimate for 34 queries: agent 408000 in / 51000 out, judge 136000 in / 20400 out (rough budgets). Actual in the committed run (evals/results/faithfulness.json, claude-haiku-5-5 agent, deepseek-flash judge at temperature 0, thinking disabled): agent 389307 in / 35072 out over 169 calls, judge 13865 in / 11534 out over 19 calls. Within the few-dollar budget. Result: 34 queries, 19 judged, 15 abstained (no close match), 0 errors; claims supported 147 of 219 (0.671); answers with every claim supported 0.000. All numbers are in evals/results/summary.md and copied into the README.
- A first full run was made before I added per-query diagnostics (answer_notes, graded_relevant, retrieved_doc_ids, judge_evidence_chars) and was replaced by the second (--force). First run, for the record (file not kept): 15 judged, 19 abstained, claims supported 125 of 183 (0.683), faithful answers 0.067, agent 444783 in / 37608 out, judge 10976 in / 9441 out. Total spend across both runs is about 1.0M tokens on Haiku plus about 0.05M on DeepSeek.
- Summary regenerated; the README Results section now has a Faithfulness subsection copied from summary.md and the limitation bullet updated. evals/baseline.json regenerated byte-identical.

IMPORTANT FINDING (agent, not fixed here): in the committed run 11 of the 15 abstentions are citation-format failures. The model cites excerpt numbers (0, 1, ...) instead of doc_ids, because the answer prompt lists excerpts as `[0] doc_id=59 ...`; the citation check drops them and the agent answers "no close match" although the grader accepted relevant chunks (graded_relevant is at least 1 in all 15). The other 4 returned an answer with no citations or text. So the agent abstains on 44% of gold queries mostly because of a prompt ambiguity, and the faithfulness rates describe only the 19 answers that kept a valid citation. I did not change agent/graph.py prompts (merged M2 behavior; changing it changes what M3 measures). Recommended follow-up: label excerpts without a bare bracketed index (for example "doc_id=59 | title | section") in the answer prompt, then rerun `run_faithfulness.py --force` (about 0.4M agent tokens). Also: the judge is strict (generic advice not in an excerpt counts as unsupported), so 0.000 fully faithful answers says more about answer style than about hallucination.
Also noted: the agent is nondeterministic (the two runs differ in abstentions: 19 vs 15), so the faithfulness figures are single-run.

Commands: test (`uv run pytest -q`) -> 249 passed, 7 deselected (the 7 db tests pass with `-m db`); lint (`uv run ruff check .`) -> all checks passed; format (`uv run ruff format --check .`) -> 107 files already formatted.

## Round 3
Commits (branch factory/004-m3-evals):
- 4d3dbbd Round 3: label answer excerpts by doc_id only, test excerpt-number citation failure
- 3944e68 Round 3: keep pre-fix faithfulness runs, summary shows before and after
- ba77c34 Round 3: rerun faithfulness after the prompt fix, README before and after, re-recorded transcript

Changed: src/outage_matcher/agent/graph.py (answer prompt), src/outage_matcher/evals/summary.py, tests/test_agent_graph.py, tests/test_evals_summary.py, evals/results/{faithfulness.json,summary.md,faithfulness-prefix-bug.json,faithfulness-prefix-bug-first-run.json}, README.md, docs/examples/{README.md,db-failover-split-brain.md}. gold.jsonl, baseline.json and all retrieval result files are untouched (git diff against d8a8974 is empty; baseline.json regenerates identically).

Agent fix (owner decision):
- The answer node now builds its prompt with `_answer_excerpts`: `doc_id=59 | title=... | section=...` followed by the text, with no bracketed position. `ANSWER_SYSTEM` says to cite the number after `doc_id=` and never by position. The grader prompt keeps `[i] doc_id=...` because the grade tool answers by position. `_validated_answer` (citation validation) is unchanged.
- Tests: test_answer_excerpts_are_labeled_by_doc_id_only_while_the_grader_keeps_positions (no `[0]` or `[1]` in the answer prompt, grader prompt still numbered, system prompt forbids citing by position); test_citing_an_excerpt_position_instead_of_a_doc_id_is_dropped_and_abstains (reproduces the first-run failure: citing position 0 is dropped and the answer degrades to no match, so a position can never be accepted as a citation of another document).

Re-run (real, full gold set, claude-haiku-5-5 agent, deepseek-flash judge at temperature 0): 34 queries, 27 judged, 7 abstained, 0 errors; claims supported 239 of 336 (0.711); answers with every claim supported 0.037 (1 of 27). Abstentions with a dropped citation: 0 of 7 (was 11 of 15). Of the 7 remaining abstentions, 2 had no relevant retrieval (q003, q022) and 5 are "answer had no valid citations or text" with relevant chunks accepted by the grader (q006, q009, q027, q029, q032); I did not investigate those 5 further (the model returned no usable citation list or text), a possible follow-up.
Token usage: estimate (rough budget) agent 408000 in / 51000 out, judge 136000 in / 20400 out. Actual: agent 376959 in / 34754 out over 166 calls; judge 22753 in / 17458 out over 27 calls. Plus one real `ask` (5 calls, 12573 in / 1068 out) to re-record the third transcript.

Before and after (all from recorded files, shown in summary.md and the README):
- Earlier committed run, evals/results/faithfulness-prefix-bug.json (same code except the prompt, 2026-11-13): 19 judged, 15 abstained (11 with a dropped excerpt-number citation), claims supported 147 of 219 (0.671), every-claim-supported 0.000, agent 389307 in / 35072 out, judge 13865 in / 11534 out.
- Very first run (before I added per-query diagnostics), kept as evals/results/faithfulness-prefix-bug-first-run.json, not shown in the README: 15 judged, 19 abstained, claims supported 125 of 183 (0.683), every-claim-supported 0.067, agent 444783 in / 37608 out, judge 10976 in / 9441 out. Note: the coordinator's message paired "19 answered / 15 abstained" with "125 of 183"; the correct pairs are 19/15 with 147 of 219 (committed run) and 15 judged/19 abstained with 125 of 183 (first run).
- Current run, evals/results/faithfulness.json: figures above.
- Caveats: one run each, the agent is nondeterministic, so the before and after difference is not a controlled estimate; the judge is strict (generic advice counts unsupported).

summary.py: `faithfulness*.json` files are no longer read as retrieval runs; `faithfulness-prefix-bug.json` is rendered as a before and after table and must share the gold sha256 and index version (test_earlier_faithfulness_run_is_shown_as_before_and_after_and_not_read_as_a_retrieval_run, test_earlier_run_on_another_gold_set_is_refused).

Transcripts: only the third (db-failover-split-brain.md) was re-recorded from a real run after the fix; it now gives a cited answer (doc 109). The other two were recorded before the fix and were not affected; docs/examples/README.md says so.

Commands: test (`uv run pytest -q`) -> 253 passed, 7 deselected; lint (`uv run ruff check .`) -> all checks passed; format (`uv run ruff format --check .`) -> 107 files already formatted.

## Round 4
Commits (branch factory/004-m3-evals), one per group:
- 2f666da Round 4: numpy in alphabetical order in pyproject
- a2c74be Round 4: dropped-citation note as a shared constant, record judge thinking setting in new results
- 7f13348 Round 4: disclose both pre-fix runs, noise and answered-set sizes in summary and README

Changed: pyproject.toml; src/outage_matcher/agent/{models,graph}.py; src/outage_matcher/evals/{deepseek,faithfulness,run_faithfulness,summary}.py; tests/test_agent_graph.py, tests/test_evals_faithfulness.py, tests/test_evals_summary.py; evals/results/summary.md; README.md. No agent behavior change and no new API runs. gold.jsonl, baseline.json, all retrieval results and all three faithfulness result files are byte-identical to before this round (git diff against ba77c34 is empty for the faithfulness files).

Review items addressed:
- Rules 1 and rigor notes 1-2 (disclose both pre-fix runs, noise, answered sets): `summary.py` now loads both `faithfulness-prefix-bug-first-run.json` and `faithfulness-prefix-bug.json` (`load_earlier_faithfulness` returns a list, oldest first), applies `check_comparable` to both, and renders three rows: first pre-fix run (15 judged, 19 abstained, 125 of 183, 0.683, 0.067), second pre-fix run (19 / 15, 147 of 219, 0.671, 0.000), after the fix (27 / 7, 239 of 336, 0.711, 0.037). The generated text says every row is a single draw of a nondeterministic agent, lists the answered-set sizes (15, 19, 27) and that rates are not like-for-like, gives the before ranges next to the after values, says the claim-support and all-claims-supported differences are within run-to-run noise (the two buggy-prompt runs abstained on 15 to 19 queries), and that the only clear effect of the fix is fewer abstentions (11 of 15 in the second pre-fix run were dropped citations, 0 of 7 after; the first run recorded no notes, so it cannot be counted). The main faithfulness section also says it is a single run and that the rates cover only the judged answers. README Results copies these blocks; the "each figure comes from one run" sentence is replaced by "three runs exist ... all single draws".
- Rigor note 4 and request (3), unexplained abstentions: summary.py now splits the current abstentions from the rows (`_abstention_breakdown`): 0 dropped citation, 5 with relevant chunks but no valid citation or text (q006, q009, q027, q029, q032; cause not explained), 2 with no relevant retrieval. The README states the five are unexplained and uninvestigated and that 27 of 34 is not the agent's ceiling.
- (4) thinking=disabled: not edited into the existing result files (they stay untouched). New runs record `config.judge_thinking` (from `deepseek.THINKING`, tested in test_result_document_records_models_judge_prompt_and_temperature); summary.py prints "thinking ..." when the field exists. The README states the setting and that the current result files predate the field.
- (5) dropped-citation count: `DROPPED_CITATION_NOTE` in agent/models.py is used by graph.py to build the note and by evals/faithfulness.py (`abstained_after_dropped_citation`, `abstained_with_relevant_chunks`), which summary.py calls. Tests: test_abstention_classifiers_use_the_agents_dropped_citation_note, and the agent test now matches on the constant.
- (6) numpy now sits after lxml in pyproject.toml; `uv lock --check` passes (uv.lock unchanged).
Tests added or changed: test_both_earlier_runs_are_shown_with_a_noise_statement_and_not_read_as_retrieval_runs, test_current_run_abstentions_are_split_into_dropped_unexplained_and_no_retrieval, test_either_earlier_run_on_another_gold_set_is_refused, plus the updated summary fixtures.

Commands: test (`uv run pytest -q`) -> 255 passed, 7 deselected; lint (`uv run ruff check .`) -> all checks passed; format (`uv run ruff format --check .`) -> 107 files already formatted.
