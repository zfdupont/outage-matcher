VERDICT: CHANGES

Checked at HEAD ba77c34 (matches commands.md: 253 passed, ruff check clean, ruff format clean; not rerun). Round 1 had no CHANGES items; its two non-blocking notes (dashes in gold.jsonl data, README wording about the faithfulness run) are unchanged or resolved.

Findings:

1. README.md:101-129 (and the summary.py text that generates the same table in evals/results/summary.md), before/after framing is not honest about run count. The README says "the earlier run" and "each figure comes from one run", and the before row is `faithfulness-prefix-bug.json` (0.671 claim support, 0.000 every-claim-supported). But a second pre-fix run is committed as `evals/results/faithfulness-prefix-bug-first-run.json` (15 judged, 19 abstained, 125 of 183 = 0.683, every-claim-supported 0.067), and build.md line 93 says it is "not shown in the README". The omitted run has a higher every-claim-supported rate (0.067) than the after run (0.037), so the table's 0.000 to 0.037 reads as an improvement that the repo's own data does not support. Abstentions across the two pre-fix runs were 19 and 15 against 7 after, and claim support was 0.683 and 0.671 against 0.711. Fix: state in the README and in the generated summary that two pre-fix runs exist (the nondeterminism is visible between them), add the first-run row to the before/after table or give the range for the before figures (judged 15-19, abstained 15-19, support 0.671-0.683, every-claim-supported 0.000-0.067), and say that the support and every-claim differences are within run-to-run noise. Correct "each figure comes from one run" to match. Regenerate summary.md and re-run the summary tests.

Checklist results (all other items pass):
- Secrets: no key-shaped strings in tracked files at HEAD; no `.env` or `evals/cache/` tracked; `.gitignore` ignores `evals/cache/`; `.env.example` holds placeholders only (`your-key-here`, `change-me`, public model ids). The three transcripts under docs/examples/ contain the question, tool calls with doc ids, answer, citation URLs (public postmortems) and token counts only; no keys, no env values, no local paths.
- Emojis and em-dashes: none in added lines outside `evals/gold.jsonl` (checked diff for U+2014, U+2013 and emoji ranges); commit messages clean.
- Co-Authored-By / generated-by: none in the 17 commit messages on the branch.
- Data source terms: no new source; transcripts quote only short model-written answers and public URLs.
- Meta/employer data: none.
- README numbers: all Results figures match `evals/results/summary.md` and the result JSON. Faithfulness: 34 queries, 27 judged, 7 abstained (sum of `no_match` in faithfulness.json is 7), 239 of 336 = 0.711, 0.037, tokens 376959 / 34754 and 22753 / 17458 match `metrics` and `tokens` in faithfulness.json. Before row: 19 judged, 15 abstained (matches per_query count), 147 of 219 = 0.671, 0.000, matches faithfulness-prefix-bug.json. Gold sha256 (23e49b91b78f) and index (34c67d0bba77, 235 / 4482) are identical across all faithfulness and retrieval files. Retrieval and corpus numbers are unchanged from round 1.

Non-blocking:
- Both `faithfulness.json` and `faithfulness-prefix-bug.json` record `code_commit` values (3944e68 and 18a48f4) that differ from the commit that made the run's prompt state, so the "before" file's commit is the pre-fix tree and the "after" file's commit is the fix commit minus the README commit. Fine, just worth knowing if someone re-derives them.
- `evals/gold.jsonl` q011, q031 (em-dash in generated query text) and q026 (en-dash in a source heading) remain, as noted in round 1; editing them would change the gold sha256 and force every run to be redone.
