# Backlog

## Follow-ups from job 001-m1-ingest-index
- [ ] Store embedding model ids in an index_meta table and check them at query time (src/outage_matcher/db.py, search.py)
- [ ] Pass bodyless parent headings down to child sections as context (src/outage_matcher/ingest/chunk.py)
- [ ] Diversify search results by document (src/outage_matcher/search.py)

## Follow-ups from job 003-m2b-ops-skeleton
- [ ] Remove the unreachable ImportError branch in get_tracer and list observability in CLAUDE.md Architecture (src/outage_matcher/observability.py)
- [ ] Add a lock around the lazy agent factory in api/app.py
- [ ] Add a request timeout around agent.ask in /ask
- [ ] Run CI once per PR instead of on both push and pull_request (.github/workflows/ci.yml)
