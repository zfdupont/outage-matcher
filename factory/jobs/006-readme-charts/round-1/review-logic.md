VERDICT: PASS

No correctness defects found. Checked at HEAD b9d41b7, the sha recorded in round-1/commands.md (test 353 passed, lint and format clean, so no rerun).

Checklist against src/outage_matcher/evals/charts.py:

- Plotted values come from the result files. `retrieval_figure` plots `run.metrics[key]` unrounded. `faithfulness_figure` plots `metrics.answered_and_judged`, `no_match` and `claim_support_rate`. `rank_change_figure` plots `Run.ranks`. All loading goes through the `summary` loaders, `n` is `gold.queries`, and no number is typed in. The committed `summary.md`, `summary.py` and `evals/` are untouched (empty `git diff --stat`). I read the three PNGs: the retrieval bars, the 15/19/27 judged counts and the 0.68/0.67/0.71 rates agree with the README tables.
- Rank-change cap and bin. `binned_rank` (charts.py:59) returns the rank when it is at most 10 and otherwise 11, so None and every rank above 10 share one bin. The x ticks are 1..10 plus `not in top 10` at 11 (charts.py:177). Rows sort by (baseline bin, reranked bin, id) (charts.py:158). The image shows 14 rows at baseline 1, which matches recall@1 = 0.412 (14 of 34), and 8 rows in the top-10-miss bin.
- Figure counts against the captions. Four retrieval bars per group, three faithfulness runs, and 34 rank rows. The captions add no metric value. The "ranks beyond 10 share one bin" caption matches the code.
- Errors fail clearly and nothing is written. `build_figures` runs `check_comparable`, `pick_baseline`, the missing `faithfulness.json` and no-earlier-run checks, the exactly-one-reranked-run check and the `metrics.queries` against `gold.queries` check. It raises `ValueError` for each, and `main` prints `error: ...` and returns 1 before `mkdir` or `savefig` (charts.py:237-246), so no partial output. An empty or missing results dir lands in `pick_baseline`'s ValueError. A `JSONDecodeError` is a `ValueError` subclass, so a malformed result file is also reported as `error:`.
- Optional segments. `errors` is added only when some run has `metrics.errors` above 0 (charts.py:126). A null `claim_support_rate` is filtered out, so it gets no bar and raises nothing (charts.py:140-142).
- matplotlib isolation. It is in `[dependency-groups] dev` and `requirements-dev.txt` only. The only file under `src/` that mentions `matplotlib` or `charts` is `charts.py`, which nothing imports. The Dockerfile uses `uv sync --frozen --no-dev`, so the image is unaffected.
- No network calls are involved. The module only reads local files.

Non-blocking notes (not defects, no action required):
1. charts.py:84-85 compares `Run` dataclasses with `in`, which compares the whole `data` dict. It works, but identity is cheaper. Not worth a change.
2. A result file with a missing key (for example no `per_query`) raises `KeyError` and gives a traceback instead of `error:`. `summary` has the same behavior and the spec lists no such case.
