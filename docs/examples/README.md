# Example transcripts

Transcripts are produced by real runs only: `ANTHROPIC_API_KEY` must be set to a real key in the
environment or `.env`, and the index must be loaded (`outage-matcher ingest`).

    uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" \
      --transcript docs/examples/lb-config-push.md

Each transcript records the date, model, tool calls, grading counts, rewrites, answer, citations
and token usage. No transcripts have been recorded yet.
