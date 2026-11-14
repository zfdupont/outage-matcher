# Search

Ranked retrieval of postmortem chunks from the pgvector index, per embedding model.

## Sub-features
- two models (bge, minilm), `--model` to pick one
- `--k` bound (1 to 1000), `--system-type` filter

## How to get to it (user POV)
`uv run outage-matcher search "<symptoms>"`

## Driving it with the CLI
```bash
set -a; . .verify/env; set +a
uv run outage-matcher search "database failover caused split brain" --k 5 | tee .verify/evidence/search.txt
uv run outage-matcher search "x" --k 0; echo "exit=$?"   # expect a one-line error, exit nonzero, no traceback
```
Proof: two ranked lists, each hit has a title, section type, score and a URL; at least one URL is in `data/manifest.jsonl`.

## Gotchas
- First run downloads embedding model weights (cached afterwards).
- With an empty index it prints a hint instead of failing: run `doctor.sh`.
