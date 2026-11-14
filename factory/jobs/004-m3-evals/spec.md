# Milestone job: build every step in order, one commit per step, no separate spec.

## Conventions

- One commit per step, brief messages, no Co-Authored-By lines, no emojis or em-dashes.
- Run `commands` (test, lint, format) after the last step; all must pass.
- Tests run offline: fake the Anthropic client and embedding models; mark anything needing network or Postgres with a pytest marker and skip it by default.
- Never commit secrets or `.env`. Read config from env vars listed in `.env.example`.
- Never invent or estimate metrics. Any number written into README.md must come from a recorded run whose output is committed under `evals/results/` (or `data/` for corpus stats).
- Use `uv add` for dependencies (it updates pyproject.toml and uv.lock); keep requirements.txt and requirements-dev.txt in sync with pyproject.toml.
- A step marked `[ESCALATE: why]` stops the milestone for the owner before merge.

## M3. Evals

**Goal:** a labeled gold set, retrieval and faithfulness metrics, and a measured baseline vs. improvement comparison.

**Steps:**
1. `evals/build_gold.py` creates about 40 gold queries: pick postmortems with a clear root-cause section; hold that section out of the index for the query (exclude from retrieval during eval) and use an LLM (DeepSeek chat API, OpenAI-compatible at https://api.deepseek.com, key in env `DEEPSEEK_API_KEY`, model `deepseek-chat`, via the `openai` SDK or httpx; add the variable to `.env.example`) to write a symptoms-only query that does not use the root-cause wording; label the source doc as relevant and manually-checkable near-duplicates when the LLM suggests them. Save `evals/gold.jsonl` with doc ids, the held-out chunk id and generation notes. Record the generation model and date.
2. `src/outage_matcher/evals/metrics.py`: recall@k (k=1,3,5,10) and MRR with unit tests on hand-checkable cases; `evals/run_retrieval.py` computes them for a given embedding model, chunking strategy and optional reranker, writing `evals/results/<run-name>.json` (config, date, index version, per-query ranks).
3. Compare the two embedding models on the gold set (baseline = section chunking with the better of the two). Add one improvement and measure it on the identical gold set: a reranker (a local cross-encoder via fastembed or an LLM rerank) or an alternative chunking strategy (e.g. section-plus-neighbor context, or fixed windows). Record both runs in `evals/results/`.
4. LLM-as-judge faithfulness `evals/run_faithfulness.py`: run the agent on every gold query; a DeepSeek judge (`deepseek-chat`, temperature 0; a different model family from the Anthropic agent, state this in the README) scores whether each claim in the answer is supported by the cited chunks (record judge prompt, model, temperature in the result). Keep API cost to a few dollars; print estimated and actual token usage.
5. Write `evals/results/summary.md` generated from the result files (table baseline vs. improvement) and add the committed baseline file used for regression checks in M4 (`evals/baseline.json`) with a stated tolerance.
6. README gains a Results section whose every number is copied from `evals/results/summary.md`. Include the limitation that queries are synthetic.

**Observable:** `uv run python -m outage_matcher.evals.run_retrieval --help` and the committed results show recall@k and MRR for each configuration.

