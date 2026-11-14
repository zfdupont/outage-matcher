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

## Follow-ups from job 004-m3-evals
- [ ] Investigate the 5 unexplained abstentions (q006, q009, q027, q029, q032) in evals/results/faithfulness.json
- [ ] Repeat the faithfulness run several times and report a mean and spread (evals/run_faithfulness.py)
- [ ] Strip dashes from gold queries only if the whole eval is rerun (evals/gold.jsonl)

## Follow-ups from job 005-m4-ops
- [ ] Watch the first GitHub Actions run of eval.yml and fix what only shows up there (.github/workflows/eval.yml)
- [ ] Identity-check the confirmed near-duplicate doc ids in gate index, not just existence (src/outage_matcher/evals/gate.py)
- [ ] Commit the gate output behind the index version cited in docs/ci-eval-gate.md
