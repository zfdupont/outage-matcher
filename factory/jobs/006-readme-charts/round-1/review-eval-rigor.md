VERDICT: PASS

Scope: HEAD b9d41b7 matches the sha in round-1/commands.md (pytest 353 passed, ruff check and format clean, all exit 0); I did not rerun commands. I viewed all three PNGs and read the README, CLAUDE.md and charts.py diffs.

Checks against the evaluation-honesty list:

1. No new measurement. `git diff main HEAD --stat` over `evals/` (results, gold.jsonl, baseline.json), `summary.py` and `tests/test_evals_summary.py` is empty: all unchanged versus main. charts.py reads only through the summary loaders, so every plotted value is a recorded field. Nothing here touches held-out root-cause text, the judge, or the gate, so those checks are unaffected.
2. Bar axes start at zero. Retrieval y is fixed to (0, 1) (charts.py:103). The faithfulness count panel is (0, n) (charts.py:135) and the rate panel (0, 1) (charts.py:143). Confirmed in the PNGs.
3. Faithfulness figure shows all three runs (first and second pre-fix, post-fix), in oldest-first order. Its suptitle reads "n=34 synthetic queries, each bar a single nondeterministic run". The rate axis label says "judged answers only", and the README caption repeats both points. The count panel shows the differing answer-set sizes (15, 19, 27 judged), so the rate bars are not presented as like-for-like.
4. Rank-change figure labels the capped bin `not in top 10` on the x axis. The caption says ranks beyond 10 share one bin and that moves inside it are counted in the table's better / worse / same column but do not show. I checked this against the plot. It shows 9 better, 4 worse and 21 same, against the table's 10 / 5 / 19, so one better and one worse move are hidden inside the capped bin, and the caption's explanation covers exactly that difference.
5. n=34 synthetic is in every figure title (derived from `gold.queries`, not hardcoded). The README intro also states 34 synthetic queries.
6. Nothing implies significance. No error bars or p-values are drawn, there are no numeric annotations, and the captions add no claims. The existing README sentence that the faithfulness differences are within run-to-run noise sits right below the figure. The small gap between 0.683, 0.671 and 0.711 in the right panel could look like a trend, but the title and caption label them as single runs, so I do not count it as a defect.
7. README changes are additions only (15 lines added, none removed). CLAUDE.md gets one Commands line and the `charts.py` entry in Architecture.

Findings: none that require changes.

Non-blocking note: the retrieval y label "score (recall is a fraction of queries)" is slightly loose for MRR. It is not misleading, so no change is needed.
