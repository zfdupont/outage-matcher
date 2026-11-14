VERDICT: PASS

Scope: round 1 (job file also holds round 2), HEAD 5ee8192, matching round-1/commands.md (test 311 passed, 7 deselected; ruff check clean; ruff format clean; all exit 0). I did not rerun commands.

Checks against the hard rules:

- Secrets: no key, token or password value in any added line, doc, test or the workflow. `.env` is ignored (`.env`, `.env.*`, `!.env.example`) and only `.env.example` is tracked; it holds `your-key-here` and `change-me` placeholders. `eval.yml` reads `ANTHROPIC_API_KEY` and `DEEPSEEK_API_KEY` only through `secrets.*`, only in the `keys` job (non-empty test, never echoed) and the final faithfulness step. The retrieval job gets none, and `permissions: contents: read` is set. The DB service uses trust auth, so no password is stored. `inputs.limit` goes through `env` and not inline in the shell, so there is no expression injection. Error handlers in `api/app.py` return fixed messages with no detail, and the tests assert that a leaked `password=` or URL text does not reach the response body. The handlers do log `exc` server-side. That text comes from psycopg, anthropic or `RetrievalError`, and none of them embeds a key or DSN password, so this is not a defect.
- Public-repo docs: `docs/compose-ask-example.md`, `docs/tracing.md` and `docs/ci-eval-gate.md` hold no hostnames beyond `localhost`, no `/Users/` paths, no personal data, no IPs and no secrets. URLs in the example response are public postmortem sources. `LANGFUSE_HOST` appears only as the public default `https://cloud.langfuse.com`.
- Emojis and em-dashes: none in added lines (grep for U+2014, U+2013 and the emoji ranges is empty).
- Commit text: no Co-Authored-By, Generated-with or Claude lines in any of the 7 branch commits.
- Data sources: no new source. `fetch-raw` fetches only the committed manifest's pages with the existing robots and size checks. `docs/sources.md` is unchanged and still excludes Meta and employer hosts. No Meta or employer data was added.
- README numbers: the diff adds no metric. The only figures are the 0.05 tolerance (it is in `evals/baseline.json`) and the 2 percent structural-drift threshold, a rule constant from `gate.py` and not a measurement. The Results section is untouched. `index_documents` 235 and `index_chunks` 4482 in `baseline.json` match `evals/results/bge-section.json` (lines 15-16).
- Untested workflow: README states "The workflow has not been run on GitHub", and `docs/ci-eval-gate.md` and the `eval.yml` header say the same.
- Dependencies: no change to `pyproject.toml` or `uv.lock`, so requirements sync is not at issue.

Non-blocking notes (no change required):

1. `docs/ci-eval-gate.md` and `docs/compose-ask-example.md` cite the index version `71c971dcffee` and 236 pages from local runs, and no file under `evals/results/` records them. They are docs only and not in the README. `build.md` says so. If you want them traceable, commit the gate output of that run.
2. `evals/baseline.json` `rule` says "see evals/gate.py". The file is `src/outage_matcher/evals/gate.py`. The text is cosmetic, and fixing it means regenerating via `summary.py`.
3. Same-repo pull requests do run the faithfulness job with the API secrets against PR code. This is the intended design and is limited to writers on the repo. The owner should know this when reading the ESCALATE workflow.
