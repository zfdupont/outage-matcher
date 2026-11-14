Add matplotlib charts to the README, generated only from recorded result files.

- Add matplotlib as a dev dependency (`uv add --dev matplotlib`).
- Write `src/outage_matcher/evals/charts.py` with a module entry (`python -m outage_matcher.evals.charts`) that reads `evals/results/*.json` (reuse the loader code `summary.py` uses; do not recompute metrics by hand and do not hardcode numbers) and writes PNGs under `docs/img/`:
  1. Grouped bars of recall@1/3/5/10 and MRR for bge section, minilm section, bge neighbor chunking, and bge + rerank.
  2. Faithfulness before/after the citation-prompt fix: abstained vs judged counts for ALL pre-fix runs and the post-fix run, plus claims-supported rate, labeled as single nondeterministic runs.
  3. Per-query rank change, baseline (bge section) vs reranked: rank of the gold document per query as a paired dot plot or scatter, capped at k=10 with a not-found bin, from the per-query ranks in the result files.
- Accessible colors, labeled axes, titles stating n=34 synthetic queries, light background, dpi 150, small file sizes.
- Embed the figures in the README Results section next to the existing tables with one-line captions; keep every existing number and table unchanged.
- Unit test: the chart module reads the result files and produces non-empty PNGs, and a bar's plotted values equal the values in `evals/results/summary.md`.
- `summary.py` must not change behavior. Update CLAUDE.md Commands. No new measurements, no API calls. Commit the PNGs (small) so the README renders on GitHub.
