VERDICT: PASS

Scope: M1 only (ingest, chunk, embed, index, search CLI). The agent graph, tool-use loop and citation checks are not built yet and are out of scope for this round. round-2/commands.md has no sha line. Its results are 54 passed, ruff clean, format clean. The worktree HEAD is 84ae035, and the build.md round 2 commit list ends at that sha. I did not rerun the test suite. I ran probes against the chunker, the real data/raw corpus and the live index.

Round 1 items, each checked:

1. Short sections dropped (chunk.py): fixed. Only a document with under 40 chars of total body yields no chunks. A probe with short Impact and Fix sections kept both with their headings. `test_short_sections_are_kept_with_their_heading` covers it.
2. Text outside block tags lost (chunk.py): fixed. The `_SectionBuilder` DOM walker keeps loose text and br-separated lines. I compared token multisets of the main container text and the chunk text across all 236 raw files. No document lost more than 2% of its tokens. The only extra tokens come from the heading prepended to each chunk, and from pages that repeat the same text themselves. The longest chunk in the corpus is exactly 1000 chars, and none go over, so the heading is now budgeted into the cap.
3. k above ef_search and filter under-return (search.py): fixed. Against the live index, `search --model bge --k 100` returned 100 rows and `--model minilm --k 1000` returned 1000. A `--system-type database` filter returned results, and an unknown type printed "no results". k=1001 gives `error: k must be between 1 and 1000`. The `db` test asserts k=100 returns 100 rows and a rare filter returns 5 rows.
4. Empty ingest wipes the index (index.py, cli.py): fixed. `write_index` raises `EmptyIndexError`, and `cmd_ingest` exits 1 before connecting or writing stats. Tests cover both.
5. Raw tracebacks (cli.py): fixed. `positive_int` validates `--k` and `--max-docs`. `main()` catches `psycopg.OperationalError`, `RuntimeError` and `ValueError` and exits 1 with an `error:` line on stderr. I confirmed an unreachable database ends in `error: ...` and exit 1. Tests exist for k 0, -3 and x, for an unreachable database and for a missing DATABASE_URL.
6. Collection failure handling (collect.py): fixed. `FETCH_ERRORS` covers `httpx.InvalidURL` in `fetch_one` and `_load_robots`. A bad URL, including one that makes `urlparse` raise, becomes an "invalid url" failure. Index-page failures are logged. The manifest and failures file are written in a `finally` block. Tests cover all three cases.

Checklist against the M1 scope:
- Chunking: no body text is dropped or duplicated on the real corpus. The headingless fallback works, and tests use fixture HTML.
- Vector search: an empty index gives an honest "no results". k over the corpus size returns what exists. An unknown model gives a clear `ValueError`.
- Network calls: the 20s client timeout, robots handling and rate limit are present. Failures surface as logged skip reasons. Tests use `MockTransport` and fakes, and the `db` tests are deselected by default.

Non-blocking, for M2 or later:
- A heading with no body of its own is still dropped. Two raw documents show it. One example is a GitHub report whose dated incident h2 ("September 13 09:16 UTC (lasting 1 hour and 28 minutes)") contains only a figure, and that heading text is lost. A bodyless parent h2 followed by h3s loses its context for the children. Fix idea: carry the pending heading into the next section's heading line, or emit it as a chunk of its own.
- No model id or dimension is stored with the index. `search` selects the column by model key, so a change to the key-to-model mapping in `MODELS` would query mismatched vectors without any error. `embed_query` output is not checked against `EMBEDDING_DIM`. An `index_meta` table with a startup check would fix this. Take it up before M2 builds on the index.
- `src/outage_matcher/cli.py:53`: with an unreachable database, psycopg's multi-line "Multiple connection attempts failed" message is printed as is, so it is not strictly one line. It is still clear. Also, a filter that matches nothing prints "is the index empty?", which is slightly misleading.
