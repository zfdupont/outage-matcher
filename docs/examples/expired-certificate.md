# Agent run

- Date: 2026-11-13
- Model: claude-haiku-5-5

## Question

all HTTPS requests to our API started failing with certificate errors at midnight

## Steps

- tool `search_incidents` {"query": "all HTTPS requests to API failing with certificate errors after midnight", "k": 5}: ok, doc_ids [188, 200, 203, 211, 217]
- grade: 2 of 5 chunks relevant

## Answer

```
Likely cause: Most likely an expired TLS certificate (the excerpts do not mention our API specifically). Excerpt 217 describes an expired TLS certificate used for internal service-to-service communication causing widespread failures, with a full recovery after replacing the certificate and restarting services. Excerpt 203 describes a different case: a CDN-side configuration change that bound an unexpected SSL certificate to production IPs, causing TLS verification failures. The midnight timing fits an expiry that rolled over at that time, but the excerpts do not confirm which certificate expired or where. This is a partial match based on analogous incidents, not a confirmed diagnosis.
Suggested fix: Check the certificate chain and expiry date presented by the API endpoints (e.g., with openssl s_client) and compare against the time failures began. If the certificate has expired, replace it and restart the affected services, as was done in excerpt 217. If the certificate is valid but unexpected, check for recent CDN or DNS configuration changes and remove the incorrect certificate binding, as in excerpt 203. Afterwards, add expiry alerting and automate renewal for the certificate, and audit other manually managed certificates.
Citations:
  [217] GitHub Availability Report: November 2025 (other)
      https://github.blog/news-insights/company-news/github-availability-report-november-2025/
  [203] GitHub Availability Report: March 2023 (other)
      https://github.blog/news-insights/company-news/github-availability-report-march-2023/
```

Usage: 4 LLM calls, 7132 input tokens, 873 output tokens, 0 query rewrites
