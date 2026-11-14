VERDICT: PASS

Reviewed at worktree HEAD 7f13348 (new commits ba77c34..7f13348). round-3/commands.md shows pytest 255 passed (7 deselected), ruff check clean and ruff format clean. The file records no sha, so I took it as current for HEAD and did not rerun the suite. I did run `python -m outage_matcher.evals.summary` into the scratchpad. It reproduced evals/results/summary.md and evals/baseline.json byte for byte, so the committed summary is current. No real defects found. Non-blocking notes follow the checks.

What I checked

1. Generated summary against the result files. I recomputed from the three faithfulness files and every number matches.
   - First pre-fix run: 15 judged, 19 abstained, 125 of 183 claims (0.683), all-claims-supported 0.067.
   - Second pre-fix run: 19 judged, 15 abstained, 147 of 219 claims (0.671), all-claims-supported 0.000.
   - Current run: 27 judged, 7 abstained, 239 of 336 claims (0.711), all-claims-supported 0.037.
   - The two numbers in the "answered sets differ in size (15, 19, 27 answers)" line are right.

2. Abstention breakdown (summary.py:195-201, faithfulness.py:154-166).
   - Current run: 0 dropped-citation, 5 with relevant chunks and no valid citation (q006, q009, q027, q029, q032), 2 with none. This matches the file and the README.
   - Second pre-fix run: 11 of 15 abstentions carry the dropped-citation note. This matches the "11 of 15" line.
   - First pre-fix run: no `answer_notes` on any of its 34 rows, so it cannot be counted. summary.py excludes it from the count, and the "Runs without per-answer notes cannot be counted" sentence is shown. That is honest.
   - The 11 of 15 and 0 of 7 are counted by the shared `DROPPED_CITATION_NOTE` constant (agent/models.py:15). The agent (graph.py:362) and the eval counter (faithfulness.py:154) both import it, so the prefix cannot drift. The old substring match `"dropped citation" in n` is gone, and `startswith` on the constant is stricter and correct. Tests cover the three-way split.

3. check_comparable covers the new files. `load_earlier_faithfulness` returns both pre-fix files when present, and `check_comparable` includes `(faithfulness, *earlier)` in the gold-sha and index-version sets (summary.py:77-84). `test_either_earlier_run_on_another_gold_set_is_refused` mutates each earlier file in turn and expects a refusal. The three committed files share gold sha 23e49b91b78f, index 34c67d0bba77 and an identical judge_prompt block, with the judge model deepseek-flash and temperature 0.0 in all three. Only the answer prompt differs between the pre-fix files and the current one.

4. The noise claim is justified by the data.
   - Claim-support rates of 0.683, 0.671 and 0.711 sit on 183 to 336 claims. A binomial standard error at p of about 0.7 is about 0.03 to 0.034. The spread of 0.04 is about one standard error, so "within run-to-run noise" is fair. The two runs with the same buggy prompt differ by 0.012, and by 4 abstentions and 36 claims.
   - All-claims-supported is 0 of 19, 1 of 15 and 1 of 27, which carries no signal either way. The text does not claim one.
   - "The only clear effect of the fix is fewer abstentions" is supported by the mechanism. 11 of 15 abstentions in the second pre-fix run were dropped excerpt-number citations, against 0 of 7 now, and the prompt diff is the only change between the runs. The abstention totals (19, 15, then 7) are consistent with it.
   - The README no longer presents 0.671 to 0.711 as a gain. This closes round-2 notes 1 and 4. It also states that the five q006/q009/q027/q029/q032 abstentions are unexplained and that 27 of 34 is not the agent's ceiling.

5. judge_thinking.
   - `deepseek.THINKING` is the single constant sent in the request and recorded as `config.judge_thinking` (run_faithfulness.py:163). It is rendered in summary.md only when the field is present.
   - The committed result files do not have the field. They were produced at ba77c34 or earlier, and their `config` keys end at `judge_temperature`.
   - The README says the files predate the field. The setting itself has been in the client since dead3d0, before every run, so "judge ran with thinking disabled" is true for all three runs.
   - This closes round-2 note 3.

6. Judged items and retrieval parity are unchanged from round 2. The judged items are the agent's real answers, retrieval is hidden per query, and the judge is a different family from the agent. This diff does not touch those paths.

Non-blocking notes

1. summary.py:274-278 (the "Differences ... are within the run-to-run noise" sentence) is fixed text, not computed from the data. If a later rerun moved the rates apart by more than noise, the generator would still say "within noise". That is fine for this committed snapshot. If the summary is regenerated after future runs, either compute the claim (for example, compare the spread to a binomial standard error) or reword it as an observation about these three runs.

2. summary.py:253-254 and 272 pair the `names` and filename slices with `[-len(before):]`. If only the first-run file exists, the single row is labelled "second run" and the dropped-citation note names `faithfulness-prefix-bug.json`. With both files committed this cannot happen. It would only matter if one file is deleted, so key the labels by filename instead.

3. The README names `faithfulness-prefix-bug.json` but not `faithfulness-prefix-bug-first-run.json`, which has the same gold, index and judge, and a `code_commit` of 18a48f4 that predates the diagnostics fields. The summary table labels it "first run", so it is not misleading. One line in the README naming both files would let a reader find the data behind the 15 and 19 abstention range.
