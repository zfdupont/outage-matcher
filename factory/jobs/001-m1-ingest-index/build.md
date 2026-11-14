## Round 1
Commits:
- 57bc8bf M1.1: pgvector compose service, db schema
- 3cebade M1.2: collect public postmortems, record terms checks, commit manifest
- b61b245 M1.3: parse and chunk postmortems by section
- 775d809 M1.4: fastembed embeddings and pgvector index writer
- 501dcf8 M1.5: outage-matcher CLI with ingest and search
- bd653c0 M1.6: real ingest, corpus stats, embedding comparison
- 147b7a5 M1.6: ASCII-dash titles, refresh manifest (follow-up fix: scraped titles contained en dashes, which the no-dash rule forbids; titles are now normalized and the index rebuilt)

Changed: docker-compose.yml, .env.example, pyproject.toml, uv.lock, CLAUDE.md, README.md, src/outage_matcher/{db,search,cli}.py, src/outage_matcher/ingest/{collect,chunk,embed,index,stats}.py, tests/{helpers,test_db,test_collect,test_chunk,test_embed_index,test_search,test_cli}.py, docs/{sources,embedding-comparison-m1}.md, scripts/compare_embeddings_m1.py, data/{manifest.jsonl,collect_failures.jsonl,corpus_stats.json}

Steps:
- [x] Step 1: `docker-compose.yml` (service `db`, `pgvector/pgvector:pg16`, named volume, `pg_isready` healthcheck, `${POSTGRES_*}` refs with `:?` required checks), `db.py` (DATABASE_URL via env/.env, schema with `postmortems`, `chunks`, one `vector(384)` column per model, HNSW cosine indexes), README section on pgvector vs Chroma. Tests: test_db.py (schema statements, URL handling; `db`-marked roundtrip, run against the real container and passed).
- [x] Step 2: `collect.py` with robots.txt, content-signal and meta-robots checks, per-host rate limit, generic User-Agent, deny list, resume from manifest. `docs/sources.md` records the terms check per source. Real run: 236 docs on first pass, manifest and failures committed, `data/raw` ignored. Tests: test_collect.py (httpx MockTransport, offline).
- [x] Step 3: `chunk.py` (largest-container main text, heading and bold-line sections, section types summary/timeline/root_cause/impact/remediation/other, 1000-char cap with sentence and word fallback, headingless fallback). Tests: test_chunk.py with fixture HTML.
- [x] Step 4: `embed.py` (fastembed, both models, BGE query prefix, lazy load), `index.py` (prepare_documents, batch embedding, transactional rewrite of both embedding columns), `stats.py`. Tests: test_embed_index.py with a fake embedder and a fake fastembed module (offline), plus a `db`-marked test run in a rolled-back transaction.
- [x] Step 5: `cli.py` (`ingest`, `search --model bge|minilm --k --system-type`, default prints both models), `[project.scripts] outage-matcher`, `search.py`, CLAUDE.md Commands registered. Tests: test_cli.py (fakes), test_search.py (argument checks offline, `db`-marked roundtrip).
- [x] Step 6: ran `docker compose up -d db && uv run outage-matcher ingest` for real. Results recorded in `data/corpus_stats.json`: 235 documents, 4092 chunks (cloudflare 29/563, community 103/1729, gcp 22/843, github 81/957 docs/chunks), 99 collect failures plus 1 parse failure. `docs/embedding-comparison-m1.md` has the 5-query side-by-side output and a hand-written observations section (kept to claims I checked against the tables and chunk text). README Corpus section copies numbers from corpus_stats.json only.

Observable check: `uv run outage-matcher search "database failover caused split brain"` printed cited results from both models against the live index.

Commands:
- test (`uv run pytest -q`) -> 40 passed, 3 deselected (db-marked tests are skipped by default; I ran them separately with `-m db -o addopts=""` and they passed against the running container)
- lint (`uv run ruff check .`) -> All checks passed
- format (`uv run ruff format --check .`) -> 30 files already formatted

Notes:
- Dependencies added with `uv add`: psycopg[binary], pgvector, python-dotenv, httpx, beautifulsoup4, lxml, fastembed. requirements.txt is `-e .` so it stays in sync via pyproject; no change needed. This trips the factory escalation rule for dependency changes, as expected for this milestone.
- Terms findings worth reviewing: AWS Site Terms prohibit data mining and robots, so aws.amazon.com is on the deny list (49 candidates denied: 20 AWS, 29 other deny-listed hosts such as github.com and medium.com). Cloudflare blog robots.txt carries `Content-Signal: ai-input=yes`. Azure PIRs were not used (history page exposes about 90 days via script-driven filters, no stable per-incident URLs). Terms of the many community-list hosts are not reviewed host by host; mitigation (robots, content signal, meta robots, rate limit, local-only) is documented in docs/sources.md. The archive.org terms page is script-rendered and could not be read, so it is not relied on.
- No employer (Meta/Facebook) data: hosts and list labels are denied; verified no manifest title or URL matches.
- system_type labels are keyword heuristics, not ground truth (stated in sources.md and the stats). 35 docs are labeled `other`.
- Corpus quirks visible in the comparison doc: GitHub monthly availability reports are multi-incident documents and match many queries; single docs can fill all top-k slots (query 5). Left for M2/M3 (diversify by document).
- The `.env` used locally was created from `.env.example` with a placeholder dev password and is git-ignored; nothing secret was committed.
- Sandbox note: `data/raw` (41 MB) is ignored. Re-running `ingest` resumes from the manifest and re-tries previously failed URLs.

## Round 2
Commits:
- 224be91 Strip emoji and pictographs from stored titles
- 7baf4b2 Chunker: keep short sections and loose text, budget heading in size cap
- 7909d69 Search: raise ef_search to cover k, iterative scan for filters, bound k
- 2ff84fb Guard empty ingest, validate k, clean CLI errors
- 28b9e7a Collect: tolerate malformed URLs, log index failures, save progress on abort
- c019e68 Drop unused network marker, update README status and script paths
- 84ae035 Rebuild index with fixed chunker; refresh stats, comparison and README numbers

Changed: src/outage_matcher/{search,cli}.py, src/outage_matcher/ingest/{collect,chunk,index}.py, tests/{test_collect,test_chunk,test_search,test_cli,test_embed_index}.py, pyproject.toml, CLAUDE.md, README.md, scripts/compare_embeddings_m1.py, data/{manifest.jsonl,corpus_stats.json}, docs/embedding-comparison-m1.md

Commands:
- test (`uv run pytest -q`) -> 54 passed, 4 deselected (db-marked tests run separately with `-m db -o addopts=""`: 4 passed against the live container)
- lint (`uv run ruff check .`) -> All checks passed
- format (`uv run ruff format --check .`) -> 30 files already formatted

Review items addressed:
- rules 1 (emoji in manifest title) -> added `normalize_title` (drops So/surrogate characters, ZWJ, variation selector, skin tone modifiers; keeps curly apostrophes and backticks), applied in `html_title`; test `test_title_emoji_and_symbols_are_stripped`; manifest refreshed (one title changed, the emoji one) and the stored titles in Postgres updated. 224be91.
- logic 1 (short sections dropped) -> sections are kept whenever they have any body; only a document with under 40 chars of total body yields no chunks. Test `test_short_sections_are_kept_with_their_heading`. 7baf4b2.
- logic 2 (text outside block tags lost) -> replaced the find_all plus 50% fallback with a DOM walker (`_SectionBuilder`): block tags are paragraphs, containers are recursed, loose text and `<br>` separated lines become paragraphs. Test `test_text_outside_block_tags_is_not_dropped_even_next_to_paragraphs` plus the existing br test. Side effect: tiny card or widget text inside the main container is now kept as its own section (the old largest-container test was adjusted to assert on the root-cause chunk). 7baf4b2.
- logic 3 (k above hnsw.ef_search truncated, filter under-returns) -> `search` now runs `SET LOCAL hnsw.ef_search = max(k, 40)` in a transaction, `SET LOCAL hnsw.iterative_scan = relaxed_order` when a system type filter is set, rejects k outside 1..1000, and re-sorts by score. `db` test returns exactly 100 rows for k=100 and 5 rows for a rare filter among 305 synthetic chunks. 7909d69.
- logic 4 (empty ingest wipes the index) -> `write_index` raises `EmptyIndexError` on empty docs, and `cmd_ingest` exits 1 before connecting or writing stats when nothing could be chunked. Tests cover both (the CLI test asserts no DB connect and no stats file). 2ff84fb.
- logic 5 (raw tracebacks) -> `positive_int` argparse type for `--k` and `--max-docs`; `main()` catches `psycopg.OperationalError`, `RuntimeError` and `ValueError`, prints `error: ...` to stderr, exits 1. Tests for k 0/-3/x, unreachable DB, missing DATABASE_URL. 2ff84fb.
- logic 6 (collection failure handling) -> `FETCH_ERRORS = (httpx.HTTPError, httpx.InvalidURL)` used in `fetch_one` and `_load_robots`; malformed list URLs (including ones that make `urlparse` raise) become an "invalid url" failure; index-page failures are logged; manifest and failures file are written in a `finally` block. Tests: malformed URL, index-page logging, KeyboardInterrupt mid-run keeps progress. 28b9e7a.
- maintainability 1 (`SECTION_TYPES` dead) -> removed. 7baf4b2.
- maintainability 2 (`IndexResult.failures` dead) -> removed with the unused `field` import. 2ff84fb.
- maintainability 3 (`network` marker unused) -> removed from markers, addopts and CLAUDE.md. c019e68.
- Non-blocking logic note on the 1000-char cap with heading -> heading length is now budgeted (`test_heading_is_budgeted_into_the_chunk_size_cap`). Not done: the `index_meta` table for model ids, and parent headings with no body (left for M2 or later, noted below).
- Non-blocking maintainability notes -> README status line updated; comparison script uses `STATS_PATH` and is listed in CLAUDE.md Commands.

Notes:
- The chunker fix changes the corpus counts, so I rebuilt the index (`outage-matcher ingest --skip-collect`) and regenerated `data/corpus_stats.json`: 235 documents, 4482 chunks (was 4092). README Corpus numbers were copied from the new file, and `docs/embedding-comparison-m1.md` was regenerated with its observations rewritten against the new tables (checked with keyword counts and host counts computed from the live index). The Round 1 numbers in this file are superseded.
- Not addressed, deliberately: storing model ids in an `index_meta` table (non-blocking suggestion; fine to take up at the start of M2), and giving a bodyless parent heading as context to its children.
- `factory/dashboard.html` contains checkbox symbols; it is a pre-existing factory file and not part of this work.
