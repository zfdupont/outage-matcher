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

## Follow-ups from job 002-m2-agent
- [ ] Record 3 real example transcripts under docs/examples/ and verify the default model name and tool_choice against the live API (needs ANTHROPIC_API_KEY)
- [ ] Annotate _env_number in src/outage_matcher/agent/config.py
