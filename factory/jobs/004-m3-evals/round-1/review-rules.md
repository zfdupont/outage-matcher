VERDICT: PASS

Checked at HEAD d8a8974 (matches commands.md: 239 passed, ruff check clean, ruff format clean; not rerun).

Checklist results:
- Secrets: no `.env` or `evals/cache/` tracked (`.gitignore` adds `evals/cache/`); no key-shaped strings in any tracked file at HEAD; `.env.example` adds `DEEPSEEK_API_KEY=your-key-here` and `DEEPSEEK_MODEL=deepseek-flash` (placeholder and a public model id only).
- Emojis and em-dashes: none in code, docs, README, CLAUDE.md or commit messages. See non-blocking note 1 for gold.jsonl data.
- Co-Authored-By / generated-by: none in the 9 commit messages on the branch.
- Data source terms and storage: no new source. `evals/gold.jsonl` stores doc id, URL, title, source name, held-out chunk ids/ords/heading, the generated query (max 319 chars), model/temperature/date/seed and notes. No postmortem body text is stored. Result files hold ranks and metrics only, no text.
- Meta/employer data: none found.
- README numbers: every table row and figure in Results matches `evals/results/summary.md` exactly (bge 0.412/0.588/0.647/0.735/0.519; minilm 0.265/0.412/0.559/0.765/0.391; neighbor -0.005, 6/15/13; rerank +0.127, 10/5/19; 34 queries; 235 documents, 4482 chunks; 0.029 per query). Those match the result JSON metrics, `data/corpus_stats.json` (235/4482), the 200-char neighbor setting and rerank depth 50 in the result configs. Gold sha256 in all four result files equals the sha256 of the committed `evals/gold.jsonl`. The README claims no faithfulness number and says the run has not happened, which fits the accepted 401 block.

Non-blocking notes (not CHANGES):
1. `evals/gold.jsonl` lines 11 and 31 (q011, q031) contain em-dashes inside the LLM-generated query text, and line 26 (q026) has an en-dash in a verbatim source heading. This is data, not code or docs, and editing the queries would change the gold sha256 and force every run to be redone, so I did not block on it. If you want strict compliance, normalize dashes in `src/outage_matcher/evals/gold.py` before writing and regenerate the gold set and runs.
2. README.md last Limitations bullet runs long on one line and refers to "will be recorded when that run happens". Update it when the faithfulness run lands, along with the "Faithfulness has not been run yet" line.
