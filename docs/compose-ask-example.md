# docker compose check with the real agent (2026-11-13)

`docker compose up --build` with the real agent, as a separate compose project (`-p m4`) on other
host ports so the main development database was not touched. The database was filled with
`outage-matcher fetch-raw` and `outage-matcher ingest --skip-collect` (236 manifest pages fetched,
none failed; 235 documents, 4482 chunks). Its index version is `71c971dcffee`, not the baseline's
`34c67d0bba77`; the gate treats a version change alone as a warning (see
`docs/ci-eval-gate.md`). The API key came from `.env`; no secret
appears below.

## Health

The container's own `HEALTHCHECK` reported `healthy` and the container runs as uid 10001 (non-root).

```
HTTP/1.1 200 OK
date: Sat, 14 Nov 2026 06:27:32 GMT
server: uvicorn
content-length: 15
content-type: application/json

{"status":"ok"}
```

## POST /ask

```
curl -s -X POST localhost:18000/ask -H 'content-type: application/json' \
  -d '{"question": "checkout latency spiked after a config push to our load balancers"}'
```

Response (pretty-printed, otherwise verbatim):

```json
{
  "answer": "Likely cause: The excerpts do not describe this incident directly; they contain no information about a config push to load balancers or checkout latency. The closest analogues are: (doc_id=187) a host upgrade that reduced capacity because a configured connection limit was lower than it should have been, causing elevated latency and timeouts; and (doc_id=30) a feature rollout that added requests per page load, causing a concurrent session build-up on load balancers and a public outage. A plausible hypothesis is that the config push lowered load balancer connection or session limits (or otherwise reduced effective capacity), but this is inferred from analogues and is not confirmed by the excerpts.\nSuggested fix: Check the load balancer config diff from the push for connection limit, concurrency, or session/timeout settings that were lowered or changed, and compare them to prior values. If a limit is confirmed too low, restore or raise it and monitor connection counts and latency. Consider rolling back the push as a fast mitigation. Add monitoring on connection limits and concurrent sessions, as recommended in the analogous postmortem. The excerpts do not cover checkout-specific behavior or the actual config change, so this needs verification against the real incident data.",
  "likely_cause": "The excerpts do not describe this incident directly; they contain no information about a config push to load balancers or checkout latency. The closest analogues are: (doc_id=187) a host upgrade that reduced capacity because a configured connection limit was lower than it should have been, causing elevated latency and timeouts; and (doc_id=30) a feature rollout that added requests per page load, causing a concurrent session build-up on load balancers and a public outage. A plausible hypothesis is that the config push lowered load balancer connection or session limits (or otherwise reduced effective capacity), but this is inferred from analogues and is not confirmed by the excerpts.",
  "suggested_fix": "Check the load balancer config diff from the push for connection limit, concurrency, or session/timeout settings that were lowered or changed, and compare them to prior values. If a limit is confirmed too low, restore or raise it and monitor connection counts and latency. Consider rolling back the push as a fast mitigation. Add monitoring on connection limits and concurrent sessions, as recommended in the analogous postmortem. The excerpts do not cover checkout-specific behavior or the actual config change, so this needs verification against the real incident data.",
  "citations": [
    {
      "doc_id": "187",
      "title": "GitHub Availability Report: January 2024",
      "url": "https://github.blog/news-insights/company-news/github-availability-report-january-2024/",
      "section": "other"
    },
    {
      "doc_id": "30",
      "title": "Outage Postmortem: March 31, 2015",
      "url": "http://web.archive.org/web/20150404235419/https://stackstatus.net/post/115305251014/outage-postmortem-march-31-2015",
      "section": "other"
    }
  ]
}
```

A bad body is a JSON error with no stack trace:

```
curl -s -X POST localhost:18000/ask -H 'content-type: application/json' -d '{"question": ""}'
{"error":{"status":422,"message":"invalid request","detail":[{"field":"question","message":"String should have at least 1 character"}]}}
```

## Notes

- The agent is nondeterministic. The first `/ask` after the container started, with the same
  question, returned the "no close match" answer with no citations (the model was also downloading
  the embedding model on that first request, which only costs time). Two later requests, and one
  `outage-matcher ask` run against the same index, returned cited answers like the one above.
  One run per question says little about how often the agent abstains; the faithfulness results in
  the README measure that over the gold set.
- Langfuse keys were the `.env.example` placeholders in this `.env`. The first container run
  logged `Failed to export spans batch code: 401` because placeholder keys enabled tracing; tracing
  now treats a `your-...` value as unset (like `ANTHROPIC_API_KEY`), and the rebuilt container above
  logged no export errors. No trace was sent to Langfuse in this check.
