VERDICT: PASS

Scope: round 3 re-check of the two round-1 findings. Worktree HEAD bcfb478 equals the sha in round-3/commands.md (pytest 320 passed, ruff check and format clean), so I did not rerun commands.

Round-1 items:

1. Gate identity check (fixed). src/outage_matcher/evals/gate.py:112-163 (`ChunkRow`, `structural_problems`) and 282-293 (`gold_rows_in_index`). The index query now joins `postmortems` and returns document id, URL and `ord` for every gold chunk id. Each chunk must have the gold row's `doc_id`, `doc_url` and an `ord` in `held_out_ords`, or `gate index` fails with the refresh message ("ids shifted"). The faithfulness job runs `gate index` before the judge run (.github/workflows/eval.yml:163-164), so held-out chunk ids that point at the wrong chunks can no longer leak root-cause text. Tests: tests/test_evals_gate.py:191 (shifted ids that still exist), :214 (doc id, URL and ord each fail alone), :391 (`gate index` command exits non-zero).
2. Tolerance wording (fixed). docs/ci-eval-gate.md:41-43 says 0.05 is about 1.7 gold queries (one flip of 0.029 passes, two flips of 0.059 fail). It agrees with README.md. The section "Why the tolerance is 0.05" (:55-60) says the value was set in M3 before any CI run existed.

Other checks:
- `git diff main...HEAD` on evals/results/ and evals/gold.jsonl is empty.
- evals/baseline.json differs from main only by adding index_documents 235 and index_chunks 4482 and by the `rule` text. All five metric values, gold_sha256, gold_queries, index_version and tolerance are unchanged.
- The gate math and edge-case tests from round 1 still stand (fail below baseline minus 0.05, exactly at the floor passes, a version change alone warns and passes).
- Retrieval and faithfulness are compared to the baseline only after `gate index`, so both run on the same gold set and a compatible index.

No defects found.
