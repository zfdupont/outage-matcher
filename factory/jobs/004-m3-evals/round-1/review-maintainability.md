VERDICT: CHANGES

Checked at HEAD d8a8974 (matches the sha in round-1/commands.md; test, ruff check and ruff format all pass there, so I did not rerun them). Layout, module map in CLAUDE.md Architecture, .env.example (DEEPSEEK_API_KEY, DEEPSEEK_MODEL), CLAUDE.md Commands and Environment Variables, and .gitignore for evals/cache/ are all in order. The evals/*.py scripts are 6-line wrappers that import from the package, so nothing is duplicated. The spec names those paths. The pending faithfulness run and the missing example transcripts are known and accepted, so they are not findings.

1. `src/outage_matcher/evals/chunking.py:8` and `src/outage_matcher/evals/retrieval.py:15`: both do `import numpy as np`, but `pyproject.toml` (dependencies list) does not declare numpy. It resolves today only as a transitive dependency of fastembed and pgvector (`uv.lock:284`, `uv.lock:985`). Nothing in `src/` imported numpy on main, so M3 introduced a direct dependency that nobody declared. The spec says to use `uv add` for dependencies. Fix: run `uv add numpy` so `pyproject.toml` and `uv.lock` record it. `requirements.txt` is just `-e .`, so it needs no change. Confirm `requirements-dev.txt` stays in sync.

Non-blocking notes (no action needed for PASS):
- `src/outage_matcher/evals/corpus.py:24` and `:49`: `DocRow.system_type` is loaded from the database but nothing in `src/outage_matcher/evals` or `tests/test_evals*` reads it. Drop it, or use it, if you touch this file again.
- `README.md` last Limitations bullet says the judge model id "will be recorded in the faithfulness result file when that run happens". This is correct for now. Update it together with the "Faithfulness has not been run yet" line once the run exists.
