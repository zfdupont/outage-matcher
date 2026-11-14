# CI eval gate

`.github/workflows/eval.yml` runs on pull requests and on `workflow_dispatch`. It has not been run
on GitHub yet; the comparison it makes is `src/outage_matcher/evals/gate.py`, which you can run
locally (see below) and which has unit tests.

## Retrieval gate (no secrets, every pull request)

1. Start a `pgvector/pgvector:pg16` service container (trust auth, reachable only from the job).
2. Restore `data/raw` with `actions/cache`, keyed on `hashFiles('data/manifest.jsonl')`, then run
   `outage-matcher fetch-raw --strict` on every run. It downloads only the manifest pages that are
   missing from `data/raw` (same robots and size checks as the collector; the manifest is not
   modified), so it does nothing on a complete cache and everything on a miss. `--strict` fails the
   job unless every manifest page is present afterwards, so a partial cache is completed or fails
   loudly instead of being cached for good. A fresh clone has no `data/raw` because it is
   git-ignored. The cache is saved only if the whole job succeeds.
3. `outage-matcher ingest --skip-collect` builds the index from the manifest and `data/raw`.
4. `gate index` checks that the index can be scored with the gold set (the hard-failure rule
   below). A different index version alone only prints a warning.
5. `run_retrieval --model bge --chunking section --allow-index-mismatch` scores the gold set (the
   flag is needed because the gold set records the baseline's index version, and step 4 has already
   checked the ids); `gate compare` checks the result against the baseline.

## The gate rule

Recall and MRR are only comparable when the index still fits the gold set, but a tiny content
change on a source page should not block a pull request.

1. **Hard failure** (exit 1, with the instructions to refresh the baseline), only if the fresh
   index is structurally incompatible with the gold set:
   - a held-out chunk id of any gold query is missing from the index, or
   - a relevant document id (the source document, or a confirmed near-duplicate) is missing, or
   - a gold chunk id exists but names another chunk: for every gold row, the chunk's document id and
     URL must equal the row's `doc_id` and `doc_url` and its `ord` must be one of the row's
     `held_out_ords`. Chunk ids are serial numbers (`TRUNCATE ... RESTART IDENTITY` on ingest), so a
     page that gains or loses one chunk shifts every later id while all of them still exist; without
     this check the held-out chunks would stay searchable and the wrong ones would be hidden, or
   - the document count or the chunk count differs from the baseline's
     (`index_documents`, `index_chunks` in `evals/baseline.json`) by more than 2 percent.
2. **Otherwise** recall@1, 3, 5, 10 and MRR are compared with the baseline: the gate fails when any
   is below its baseline value minus the tolerance in `evals/baseline.json` (0.05 absolute, about
   one gold query; a score exactly at the floor passes). It also fails if the gold set file or the
   run configuration (embedding model, chunking, reranker) differs from the baseline's, since those
   scores are not comparable.
3. **Index version differs alone**: the index version is a hash of every document, chunk id and
   chunk text. When only it differs, the gate prints `WARNING: index version NEW differs from the
   baseline's OLD ...` (in the log, the job summary and, on GitHub Actions, as an annotation) and
   still passes if the metrics are within tolerance.

The job fails in the cases of rule 1 and rule 2 and passes with a warning in rule 3. The report is
printed and appended to the job summary. The warning is a prompt to refresh the baseline when
convenient, not a failure.

### Refreshing the baseline

To refresh the baseline after an intended corpus change:

    uv run outage-matcher ingest                       # or fetch-raw and ingest --skip-collect
    uv run python evals/build_gold.py                  # gold set tied to the new index (DeepSeek key)
    uv run python evals/run_retrieval.py --model bge --force      # and the other recorded runs
    uv run python -m outage_matcher.evals.summary      # rewrites summary.md and baseline.json

then update the README Results section from `evals/results/summary.md` and commit.

### Why the version alone does not fail

When this gate was built, a fresh `fetch-raw` and `ingest --skip-collect` of all 236 manifest
pages (none failed) gave 235 documents and 4482 chunks, the same counts and ids as the baseline,
but a different index version (71c971dcffee against the baseline's 34c67d0bba77). The only
difference was one chunk of one CircleCI forum page whose view counter had moved by one, and
`gate compare` on that index reported the same recall@k and MRR as the baseline. The owner decided
that such drift must not fail the gate, hence rule 3. Making the chunker ignore such counters would
change chunk text and would itself need a baseline refresh.

## Faithfulness job (LLM judge, manual only)

Runs only when started with `workflow_dispatch`; it never runs on pull requests. The repository is
public, the job spends API credits, and code from a pull request branch (the ingest and
`run_faithfulness` modules, the lockfile) would run with the keys in its environment. It needs the
retrieval job to pass, first checks that both `ANTHROPIC_API_KEY` and `DEEPSEEK_API_KEY` exist as
GitHub secrets (failing before the slow ingest if not; it only tests that the values are
non-empty), rebuilds the same index and runs `run_faithfulness`. It reports a result and has no
threshold: it is a single draw of a nondeterministic agent (see the README Results section).
`workflow_dispatch` takes an optional `limit` input to run only the first N gold queries and cap the
cost.

Secrets are read from `secrets.*` only in two steps of this job, are never printed, and are not
available to the retrieval job.

## Run the same check locally

    docker compose up -d db
    uv run outage-matcher fetch-raw && uv run outage-matcher ingest --skip-collect
    uv run python -m outage_matcher.evals.gate index
    uv run python -m outage_matcher.evals.run_retrieval --model bge --name ci-bge-section \
      --results-dir /tmp/eval-results --allow-index-mismatch
    uv run python -m outage_matcher.evals.gate compare /tmp/eval-results/ci-bge-section.json
