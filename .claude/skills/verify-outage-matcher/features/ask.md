# Ask (agent)

LangGraph agent: retrieve (tool use), grade, rewrite and retry (cap 2), answer with citations.

## Sub-features
- tools: search_incidents, get_postmortem, filter_by_system_type
- abstains with "no close match" when nothing relevant; citations limited to retrieved doc ids
- `--transcript PATH` writes a Markdown transcript

## How to get to it (user POV)
`uv run outage-matcher ask "<incident description>"`

## Driving it with the CLI
```bash
set -a; . .verify/env; set +a
uv run outage-matcher ask "checkout latency spiked after a config push to our load balancers" --transcript .verify/evidence/ask-lb.md | tee .verify/evidence/ask-lb.txt
```
Proof: likely cause and fix, citations with URLs, token usage; every cited doc id exists in `postmortems`.

## Gotchas
- Needs a real workspace-scoped `ANTHROPIC_API_KEY`; 401 means invalid, 400 mentioning a workspace means an unscoped key.
- The agent is nondeterministic; judge structure and grounding, not exact wording.
- Costs a few cents per run.
