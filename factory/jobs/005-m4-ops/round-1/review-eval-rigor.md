VERDICT: CHANGES

Scope: regression gate (gate.py, baseline.json, summary.py, --allow-index-mismatch use). Worktree HEAD 5ee8192 equals the sha in round-1/commands.md (pytest 311 passed, ruff check and format clean), so I did not rerun commands.

Checked and fine:
- `git diff main...HEAD` on evals/results/ and evals/gold.jsonl is empty. evals/baseline.json changes only by adding index_documents 235 and index_chunks 4482 and by the `rule` text. All five metric values, gold_sha256, gold_queries, index_version and tolerance are byte-identical.
- Gate math: a metric fails when `current < baseline - 0.05 - 1e-9`. NaN fails. A score exactly at the floor passes. Tests cover both edges per metric, and one test checks the committed baseline against a real drop (tests/test_evals_gate.py:127-134, 201-225).
- Version-only drift warns and passes. Version drift plus a regression fails and still warns (tests/test_evals_gate.py:105-121).
- Gold sha mismatch, a different embedding model, chunking or reranker, and count drift over 2 percent are hard failures in `compare` (gate.py:151-171).
- --allow-index-mismatch already exists in run_retrieval.py:163 and run_faithfulness.py:199 (not in this diff). The workflow passes it only after `gate index` runs. Without it the warning-only rule could not work.
- The 0.029 per query figure is stated in README.md:241.

Findings:

1. src/outage_matcher/evals/gate.py:104-125 and 229-234 (`gold_ids`, `structural_problems`, `present_ids`). The structural check only tests that gold chunk ids and doc ids exist in the index. It does not test that they are the same documents and chunks.
   - db.py:22,33 uses SERIAL ids, and ingest/index.py:82 does `TRUNCATE ... RESTART IDENTITY`. Ids therefore depend on manifest order and on which pages were fetched.
   - `fetch-raw` exits 0 on partial failures (build.md). If one early page fails or is added, every later document id and chunk id shifts. Counts move by about 0.4 percent, inside the 2 percent allowance, and every gold id except the last few still "exists". So `gate index` passes.
   - Retrieval then excludes by (doc_id, held_out_ords) (retrieval.py:41-46) on shifted documents. It scores the wrong documents against relevant_doc_ids, so metrics collapse. The failure is reported as REGRESSED with no refresh hint.
   - The faithfulness run excludes by `held_out_chunk_ids` (run_faithfulness.py:247). With shifted ids it hides the wrong chunks and leaves the real root-cause chunks searchable. That leaks the held-out text and inflates the judged result, and nothing flags it.
   - The gold rows already carry `doc_url`, `doc_id` and `held_out_ords`, so the fix is cheap. In `present_ids` and `structural_problems`, also verify for each gold query that `postmortems.url` for `doc_id` equals `doc_url`, and that each `held_out_chunk_ids` entry belongs to `doc_id` at the matching `held_out_ords`. Report mismatches as hard failures with REFRESH_HELP. Add unit tests with the FakeDb: shifted ids that exist but belong to another document must fail.
   - Note that the version-only warning is the only remaining signal for this case, and it passes.

2. docs/ci-eval-gate.md:34-35 says the tolerance is "0.05 absolute, about one gold query". With 34 queries, 0.05 is 1.7 queries. One flipped query (0.029) passes and two (0.059) fail. README.md:241 states one query = 0.029 correctly, so the two docs disagree. The tolerance choice itself is reasonable, but it is not justified anywhere. Fix the wording to "1.7 queries: one query changing rank passes, two fail on the same metric". Add one sentence on why 0.05, and record in baseline.json or the docs that it was fixed before any CI run.
