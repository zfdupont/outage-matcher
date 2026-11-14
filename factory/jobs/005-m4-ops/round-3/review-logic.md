VERDICT: PASS

Scope: HEAD bcfb478 matches round-3/commands.md (320 passed, 7 deselected; ruff check and format clean). I did not rerun the test commands. Reviewed the diff 5ee8192..HEAD for gate.py, db.py, cli.py, eval.yml, docker-compose.yml and the new tests.

Round-1 items:
1. Gate identity check (was CHANGES): fixed. `gate.py` `gold_rows_in_index` now joins `chunks` to `postmortems` and reads id, doc id, URL and ord. `structural_problems` fails with the refresh message when a gold chunk's doc id or URL differs from the gold row, or its ord is not in `held_out_ords`. Tests cover shifted ids that still exist, each mismatch alone, and the CLI path. I also checked it against real data. I dumped (id, postmortem_id, url, ord) from the running 001-m1 index (4482 chunks, the baseline index) and applied the same rule to all 114 held-out chunk ids in `evals/gold.jsonl`. Zero were misaligned, so the new check does not false-fail on the baseline index (a false failure would block every CI run).
2. Cache-miss-only fetch (was CHANGES): fixed. Both jobs now run `fetch-raw --strict` on every run, with no cache-hit condition. `cmd_fetch_raw` returns 1 when any manifest page is still absent. `fetch_missing_pages` fetches only absent pages, so a complete cache costs nothing. The cache is saved only when the job passes, so an incomplete corpus can no longer be cached.
3. Minor, baseline missing keys: fixed. `_load_baseline` checks `index_version`, `index_documents`, `index_chunks` and `gold_sha256`, prints a one-line "Regenerate it with ...summary" error and returns exit 2. It is used by `cmd_index` and `cmd_compare`.
4. Minor, connect timeout: fixed. `db.connect` passes `connect_timeout=10` (`db.py:70`), with `test_connect_sets_a_connect_timeout`.

New code from rounds 2 and 3 checked: the faithfulness job is `workflow_dispatch` only and fails fast on empty secrets before ingest. The secrets are used only in that job's key check and final eval step, and are never printed. `${{ inputs.limit }}` goes through env, not inline in the script. The AGENT_* compose passthrough uses empty defaults. The `--allow-index-mismatch` calls are safe because `gate index` runs first.

Non-blocking:
- `gate.py` `structural_problems`: only `row.doc_id` is identity-checked, through the gold chunks. The confirmed near-duplicate doc ids in `relevant_doc_ids` are checked for existence only. Postmortem ids are serial too, so a dropped page could shift them without detection, but that needs a manifest page to fail ingest, and the 2 percent count rule and `fetch-raw --strict` cover most of that path. If it is ever hardened, compare each near-duplicate's URL.
