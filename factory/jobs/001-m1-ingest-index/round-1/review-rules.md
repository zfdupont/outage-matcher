VERDICT: CHANGES

Checked at HEAD 147b7a5 (matches round-1/commands.md; test, lint and format all exit 0, so no command failures).

1. data/manifest.jsonl:90 - the committed title for the keepthescore.co entry ends with an emoji ("We deleted the production database by accident" followed by the explosion emoji, doc_id 08d1a980f931d211). The rule is no emojis in code, docs or committed text. The dash fix in 147b7a5 only normalized U+2013/U+2014 (src/outage_matcher/ingest/collect.py:235) and missed this. Fix: extend the title normalization at collect.py:235 to strip emoji and other pictographic symbols (for example drop characters in the Emoji/So categories, then collapse whitespace), add a unit test for it in tests/test_collect.py, and refresh the title in data/manifest.jsonl (and rebuild the index if the title is stored there; data/corpus_stats.json counts do not change). The curly apostrophes in other titles (U+2019, lines 14, 62, 69, 75, 76 and others) are not emojis or dashes and are fine.

Checked and clean:
- Secrets: no key, token or password value in any tracked file. .env is ignored (.gitignore has .env, .env.*, !.env.example) and only .env.example is tracked; it holds placeholders (your-key-here, change-me). docker-compose.yml uses ${POSTGRES_*} references with :? required checks.
- Em-dashes and en-dashes: none in added lines outside the finding above (checked U+2012 to U+2015).
- Commit text: no Co-Authored-By, Claude or generated-by lines in any of the 7 commit messages.
- Sources: docs/sources.md records the terms check per source and the local-indexing-only use. AWS and Azure are excluded with reasons. Only the manifest (URL, title, source, date, label) is committed and data/raw/ is ignored and untracked. The weak spot is the "other company blogs" row, where terms are not reviewed per host. That is stated openly with robots, content-signal, meta-robots and a deny list as mitigation, so I am not treating it as a defect.
- Meta and employer data: no facebook, fb.com, meta.com or instagram host in the manifest. engineering.fb.com is recorded as denied in collect_failures.jsonl. The meta.stackoverflow.com entry is unrelated to Meta.
- README numbers: documents 235, chunks 4092, per-source counts, 99 collect failures with the reason breakdown, 1 parse failure and the chunks-by-section counts all match data/corpus_stats.json exactly. The manifest has 236 lines, which equals 235 documents plus the 1 parse failure. The README Corpus section cites the stats file as its source.
