## Round 1
Commits: f128063 Add evals charts module and tests; b9d41b7 Add results figures to README
Changed: src/outage_matcher/evals/charts.py (new), tests/test_evals_charts.py (new), docs/img/retrieval-metrics.png, docs/img/faithfulness-before-after.png, docs/img/rank-change-rerank.png (new), README.md, CLAUDE.md, pyproject.toml, uv.lock, requirements-dev.txt
Acceptance criteria:
- [x] AC1 main writes exactly three PNGs, signature, dpi 150, under 150 KB, opaque white (0, 0) (test_main_writes_three_pngs)
- [x] AC2 retrieval bars equal summary.md cells, order and labels (test_retrieval_bars_match_summary_table)
- [x] AC3 fixture bar heights and `n=4` titles (test_fixture_bar_heights_and_titles)
- [x] AC4 faithfulness panels equal summary.md table, no errors segment, title text (test_faithfulness_panels_match_summary_table)
- [x] AC5 errors segment and null rate (test_errors_segment_only_when_a_run_has_errors, test_null_claim_support_rate_gets_no_bar)
- [x] AC6 binned_rank, marker x equals binned recorded ranks, `not in top 10` tick, row sort (test_binned_rank, test_rank_markers_match_recorded_ranks, test_rank_rows_sorted_by_baseline_then_reranked_then_id)
- [x] AC7 white faces, palette, labels, ASCII, y limits, no bar annotations (test_style_rules, test_y_limits_fixed_to_unit_interval, test_no_numeric_annotations_on_bars)
- [x] AC8 exit 1, `error: `, nothing written, for eight cases incl. the five listed (test_errors_exit_1_and_write_nothing)
- [x] AC9 committed PNGs and README links with `Figure:` caption (test_committed_png_is_valid, test_readme_links_each_image_with_a_figure_caption)
- [x] AC10 summary.md lines kept in README (test_readme_keeps_every_summary_line)
- [x] AC11 summary reproduced byte for byte; test_evals_summary.py and summary.py unedited (test_summary_md_is_reproduced_byte_for_byte)
- [x] AC12 matplotlib dev only, only charts.py imports it (test_matplotlib_is_a_dev_only_dependency, test_only_charts_imports_matplotlib)
- [x] AC13 command in CLAUDE.md and README (test_command_is_documented)
Commands: test -> 353 passed, 7 deselected; lint -> All checks passed; format -> 157 files already formatted
Notes:
- I viewed all three PNGs. Fixed layout problems: faithfulness suptitle clipped (now two lines, taller figure), its legend overlapped the x label, and the `not in top 10` tick label was clipped (wider xlim). Sizes are 55 to 96 KB.
- PALETTE is the eight Okabe-Ito colors in lowercase hex (matplotlib's `to_hex` form). Bars use blue, orange, green, vermillion only.
- Titles: retrieval and rank figures use the axes title, the faithfulness figure uses `fig.suptitle` (two lines, the `n=` and `single nondeterministic run` phrases each on one line). The legend sits below each axes via `bbox_to_anchor` so it never covers data.
- In the rank plot, when baseline and reranked are equal the circle sits under a smaller diamond (circle larger so a ring shows).
- Extra errors beyond the spec: `build_figures` also raises ValueError when the baseline and reranked runs cover different query ids. Charts only reads through summary loaders; no result file or summary.py was touched.
- AC3 fixture test also asserts `n=34` is absent from the titles.
