VERDICT: PASS

Scope: round 3 re-read of `.github/workflows/eval.yml` (in full) and `docker-compose.yml`, plus a check of the round-1 notes. The worktree HEAD is bcfb478, the same sha recorded in round-3/commands.md (320 passed, ruff check and ruff format clean), so I did not rerun anything. No defects found.

Round-1 notes, now resolved

1. Faithfulness job exposing keys to PR-branch code (round-1 note 1). `faithfulness` now has `if: github.event_name == 'workflow_dispatch'` (eval.yml:111). Pull request code never runs with the keys. The retrieval job uses no secrets and still runs on fork PRs. This is the hard boundary I suggested.
2. Partial `fetch-raw` poisoning the cache (round-1 note 2). Both jobs run `uv run outage-matcher fetch-raw --strict` on every run (eval.yml:69, 159). `--strict` is defined at `cli.py:189-193`, and `cmd_fetch_raw` returns 1 when any manifest page is still missing (`cli.py:71`). `fetch_missing_pages` skips pages already on disk (`collect.py:576`), so a complete cache costs nothing and an incomplete one is completed or fails. `actions/cache` saves only on job success, so an incomplete `data/raw` is never saved.
3. `keys` job without a timeout (round-1 note 3). The job is removed. The secret check is now the first step of the faithfulness job, which has `timeout-minutes: 90`.

Checked and fine

- Secret handling in eval.yml. Secrets appear in only two step `env:` blocks, "Require both API keys" (eval.yml:136-137) and "Faithfulness eval" (:174-175). The check step only tests `-z` and prints a fixed message. It runs before checkout, setup-uv and cache, and those never receive the secrets. No `set -x`, no `${{ secrets.* }}` inside a `run:` body, and no secret in the artifact or the step summary. `inputs.limit` goes through `env: LIMIT` and is quoted in the shell (`${LIMIT:+--limit "$LIMIT"}`), so there is no expression injection.
- Triggers and permissions. The triggers are `pull_request` and `workflow_dispatch`. There is no `pull_request_target` or `workflow_run`. Top-level `permissions: contents: read`. Concurrency group with cancel-in-progress.
- Eval gate. In the retrieval job, `gate index`, `run_retrieval` and `gate compare` are plain steps with no `continue-on-error`, so a regression fails the job. `if: always()` on the upload does not mask the failure. `faithfulness` has `needs: retrieval`, so on a dispatch run a failed retrieval gate skips the paid job.
- Pgvector service container. It uses health-cmd, interval and retries. `trust` auth means no stored password. `DATABASE_URL` matches, and the steps run on the host, so `localhost:5432` is correct.
- docker-compose.yml. All values are `${VAR}` references, with `:?` on the required DB values and `:-` defaults on the optional ones. No literals. The new `AGENT_MODEL`, `AGENT_MAX_RETRIES`, `AGENT_REQUEST_TIMEOUT` and `AGENT_API_MAX_RETRIES` are forwarded with empty defaults. `config.py` treats an empty value as unset (`_env_number` at `config.py:25-28`, `or DEFAULT_AGENT_MODEL` for the model), so an empty forwarded value does not crash the API at startup. The names match `load_config`.
- Dockerfile and `.dockerignore`. Unchanged from main and still multi-stage, non-root, with a HEALTHCHECK on `/health`. `.dockerignore` excludes `.git/` and `.env`. `/ask` model validation and the 502/503/500 mapping with generic bodies were verified in round 1, and I saw nothing in this diff that changes them.

Not verified: the workflow has not run on GitHub, so service-container startup, cache behavior and the step summary are read from the YAML only.
