# Example transcripts

Transcripts are produced by real runs only: `ANTHROPIC_API_KEY` must be set to a real key in the
environment or `.env`, and the index must be loaded (`outage-matcher ingest`).

    uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" \
      --transcript docs/examples/lb-config-push.md

Each transcript records the date, model, tool calls, grading counts, rewrites, answer, citations
and token usage. All three below are real runs on 2026-11-13 with the default model
`claude-haiku-5-5` (the live API accepted the model name and the forced tool choice).

- `lb-config-push.md`: an answer with two citations.
- `expired-certificate.md`: an answer with citations.
- `db-failover-split-brain.md`: kept as recorded although it ends in "no close match". The model
  cited the excerpt numbers 0 and 1 instead of doc ids, the citation check dropped both, and the
  agent correctly refused to return an ungrounded answer.
