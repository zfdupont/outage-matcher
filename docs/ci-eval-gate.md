# CI eval gate

`.github/workflows/eval.yml` runs on pull requests and on `workflow_dispatch`. It has not been run
on GitHub yet; the comparison it makes is `src/outage_matcher/evals/gate.py`, which you can run
locally (see below) and which has unit tests.

## Retrieval gate (no secrets, every pull request)

1. Start a `pgvector/pgvector:pg16` service container (trust auth, reachable only from the job).
2. Restore `data/raw` with `actions/cache`, keyed on `hashFiles('data/manifest.jsonl')`. On a cache
   miss, `outage-matcher fetch-raw` downloads exactly the pages the committed manifest lists
   (same robots and size checks as the collector; the manifest is not modified). A fresh clone has
   no `data/raw` because it is git-ignored. The cache is saved only if the whole job succeeds, so a
   run that could not fetch every page never poisons it.
3. `outage-matcher ingest --skip-collect` builds the index from the manifest and `data/raw`.
4. `gate index`: the index version (a hash of every document, chunk id and chunk text, as in
   `evals/results/*.json`) must equal `index_version` in `evals/baseline.json`.
5. `run_retrieval --model bge --chunking section` scores the gold set; `gate compare` checks the
   result against the baseline.

### Behavior when the index differs from the baseline

Recall and MRR are only comparable on the same index and gold set. If the freshly built index
version differs from the baseline's (a source page changed, the manifest changed, or pages could
not be fetched), the job fails at step 4 with a message that says so and tells the maintainer to
refresh the baseline. It does not compare scores and does not pass silently.

To refresh the baseline after an intended corpus change:

    uv run outage-matcher ingest                       # or fetch-raw and ingest --skip-collect
    uv run python evals/build_gold.py                  # gold set tied to the new index (DeepSeek key)
    uv run python evals/run_retrieval.py --model bge --force      # and the other recorded runs
    uv run python -m outage_matcher.evals.summary      # rewrites summary.md and baseline.json

then update the README Results section from `evals/results/summary.md` and commit.

### Known caveat: the index version is strict

The version hashes the text of every chunk, so any change on a source page changes it. When this
gate was built, a fresh `fetch-raw` and `ingest --skip-collect` of all 236 manifest pages (none
failed) gave 235 documents and 4482 chunks, the same counts as the baseline, with the same ids, but
a different index version (71c971dcffee against the baseline's 34c67d0bba77). The only difference
was one chunk of one CircleCI forum page whose view counter had moved by one. `gate compare` on that
index reported the same recall@k and MRR as the baseline and still failed on the version rule, as
designed. Expect the first CI run on a cache miss, and any later run after a source page changes,
to fail this way until the baseline is refreshed (or the baseline's `data/raw` is reused through the
cache). Making the chunker ignore such counters would change chunk text and so would itself need a
baseline refresh.

### Behavior on the same index

`gate compare` fails when any of recall@1, 3, 5, 10 or MRR is below its baseline value minus the
tolerance in `evals/baseline.json` (0.05 absolute, about one gold query; a score exactly at the
floor passes). It also fails if the gold set file or the run configuration (embedding model,
chunking, reranker) differs from the baseline's, since those scores are not comparable. The report
is printed and appended to the job summary.

## Faithfulness job (LLM judge)

Runs only when started with `workflow_dispatch`, or on a pull request when both `ANTHROPIC_API_KEY`
and `DEEPSEEK_API_KEY` exist as GitHub secrets (checked by a small job that only tests whether the
values are non-empty). It needs the retrieval job to pass, rebuilds the same index and runs
`run_faithfulness`. It reports a result and has no threshold: it is a single draw of a
nondeterministic agent (see the README Results section). `workflow_dispatch` takes an optional
`limit` input to run only the first N gold queries and cap the cost. Pull requests from forks get
no secrets, so the job is skipped for them.

Secrets are read from `secrets.*` only in the steps that need them, are never printed, and are not
available to the retrieval job.

## Run the same check locally

    docker compose up -d db
    uv run outage-matcher fetch-raw && uv run outage-matcher ingest --skip-collect
    uv run python -m outage_matcher.evals.gate index
    uv run python -m outage_matcher.evals.run_retrieval --model bge --name ci-bge-section \
      --results-dir /tmp/eval-results
    uv run python -m outage_matcher.evals.gate compare /tmp/eval-results/ci-bge-section.json
