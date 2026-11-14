VERDICT: PASS

Checked at worktree HEAD 84ae035, which matches the last commit listed in build.md Round 2. round-2/commands.md shows pytest (54 passed, 4 db-marked deselected), ruff check and ruff format --check all exit 0, so I did not rerun them.

Round 1 items:
1. `SECTION_TYPES` in chunk.py: fixed. The constant is deleted and grep finds no references in src, tests or scripts.
2. `IndexResult.failures` in index.py: fixed. The field and the unused `field` import are gone. `field` is still imported in chunk.py, where `Section` uses it.
3. The `network` marker: fixed. It is removed from the pyproject.toml markers, the `addopts` expression (now `-m 'not db'`) and the CLAUDE.md Commands line, which now reads `pytest -m db -o addopts=""`. Grep finds no `network` marker usage.
4. Non-blocking items: the README status line now says M1 is built. `scripts/compare_embeddings_m1.py` imports `STATS_PATH` and is listed in CLAUDE.md Commands.

Round 2 changes checked against the maintainability checklist:
- Layout: all new code is in the named modules (ingest/{collect,chunk,index}, search, cli). There are no new top-level scripts and no new dependencies.
- Dead code: the chunker rewrite removed `_has_block_ancestor` and the 50% fallback with no leftovers. `MIN_BODY_CHARS` is still used in `extract_sections`. `EmptyIndexError`, `positive_int`, `FETCH_ERRORS`, `MAX_K` and `DEFAULT_EF_SEARCH` are all used.
- Tests: each behavior change has a test, per the test diffs: emoji titles, short sections, loose text, the heading budget, search k and filter behavior, empty ingest, CLI errors, malformed URLs, and KeyboardInterrupt in collect.
- Config: no new environment variables or hardcoded config.
- Style: the added lines have no en or em dashes. The commit messages carry no Co-Authored-By lines.

No findings.
