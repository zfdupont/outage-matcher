# Example transcripts

Transcripts are produced by real runs only: `ANTHROPIC_API_KEY` must be set to a real key in the
environment or `.env`, and the index must be loaded (`outage-matcher ingest`).

    uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" \
      --transcript docs/examples/lb-config-push.md

Each transcript records the date, model, tool calls, grading counts, rewrites, answer, citations
and token usage. All three below are real runs on 2026-11-13 with the default model
`claude-haiku-5-5` (the live API accepted the model name and the forced tool choice).

- `lb-config-push.md` and `expired-certificate.md`: answers with two citations each (recorded
  before the answer-prompt fix; citations were not affected).
- `db-failover-split-brain.md`: re-recorded after the fix. The first recording ended in "no close
  match" because the model cited excerpt numbers instead of doc ids (see `README.md` in the repo
  root); the current one is a cited answer.
