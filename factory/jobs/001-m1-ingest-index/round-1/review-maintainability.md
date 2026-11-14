VERDICT: CHANGES

Checked at HEAD 147b7a5, which matches round-1/commands.md. pytest (40 passed, 3 db-marked deselected), ruff check and ruff format --check all exit 0. Module layout matches the CLAUDE.md Architecture (ingest/{collect,chunk,embed,index}, search, cli, db). The `outage-matcher` entry point is declared in pyproject `[project.scripts]` and listed in CLAUDE.md Commands. Config comes from env vars: DATABASE_URL and the POSTGRES_* values are all in .env.example and CLAUDE.md. Every dependency added to pyproject.toml is imported in src. The diff adds no em or en dashes and no Co-Authored-By lines. README numbers match data/corpus_stats.json. Every behavior change has a test. The findings below are all dead code, which the checklist rules out.

1. src/outage_matcher/ingest/chunk.py:27 - `SECTION_TYPES` is defined and never referenced in src, tests or scripts. Fix: delete it. If the allowed section names should be enforced, use it in a test that checks every `SECTION_RULES` label plus "other" is in it. Otherwise remove it.

2. src/outage_matcher/ingest/index.py:28 - `IndexResult.failures` is never populated or read. `prepare_documents` returns parse failures separately, and the CLI passes them to `build_stats`. The field is a misleading second place for the same data. Fix: remove the `failures` field and the then-unused `field` import from `dataclasses`.

3. pyproject.toml:42-46 and CLAUDE.md Commands (the `pytest -m "db or network"` line) - The `network` marker is registered, excluded in `addopts` and documented. No test uses `@pytest.mark.network`, and the only `pytest.mark` usages are `db`. Fix: drop `network` from the markers, from the `addopts` expression and from the CLAUDE.md line. Re-add it when a network test exists. This is a speculative abstraction.

Non-blocking, no change required:
- README.md:5 still says "Status: scaffolding", which is stale now that M1 is built.
- scripts/compare_embeddings_m1.py:28 hardcodes "data/corpus_stats.json". It could import `STATS_PATH` from `outage_matcher.ingest.stats`. The script is also not listed in CLAUDE.md Commands, although its usage is in its docstring.
