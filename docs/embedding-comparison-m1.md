# Embedding comparison, M1 (qualitative)

Generated 2026-11-13 by `scripts/compare_embeddings_m1.py` over 235 documents and 4092 chunks (`data/corpus_stats.json`). Top 5 chunks per model, one row per chunk. Scores are cosine similarity and are only comparable within one model.

## Query: database failover caused split brain

### bge (BAAI/bge-small-en-v1.5)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | GitHub Availability Report: May 2023 | other | 0.744 | https://github.blog/news-insights/company-news/github-availability-report-may-2023/ |
| 2 | GitHub Availability Report: August 2021 | other | 0.739 | https://github.blog/news-insights/company-news/github-availability-report-august-2021/ |
| 3 | GitHub availability this week | other | 0.733 | https://github.blog/news-insights/the-library/github-availability-this-week/ |
| 4 | GitHub Availability Report: March 2022 | other | 0.726 | https://github.blog/news-insights/company-news/github-availability-report-march-2022/ |
| 5 | GitHub Availability Report: April 2023 | other | 0.724 | https://github.blog/news-insights/company-news/github-availability-report-april-2023/ |

### minilm (sentence-transformers/all-MiniLM-L6-v2)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | GitHub Availability Report: May 2023 | other | 0.576 | https://github.blog/news-insights/company-news/github-availability-report-may-2023/ |
| 2 | A Byzantine failure in the real world | other | 0.545 | https://web.archive.org/web/20211015231917/https://blog.cloudflare.com/a-byzantine-failure-in-the-real-world/ |
| 3 | GitHub availability report: August 2026 | impact | 0.512 | https://github.blog/news-insights/company-news/github-availability-report-august-2026/ |
| 4 | Incident Review: What Comes Up Must First Go Down | remediation | 0.510 | https://www.honeycomb.io/blog/incident-review-what-comes-up-must-first-go-down/ |
| 5 | An update on recent service disruptions | other | 0.506 | https://github.blog/2022-03-23-an-update-on-recent-service-disruptions/ |

## Query: expired TLS certificate took down the API

### bge (BAAI/bge-small-en-v1.5)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | GitHub Availability Report: November 2025 | other | 0.760 | https://github.blog/news-insights/company-news/github-availability-report-november-2025/ |
| 2 | GitHub availability report: July 2026 | other | 0.717 | https://github.blog/news-insights/company-news/github-availability-report-july-2026/ |
| 3 | GitHub Availability Report: March 2023 | other | 0.696 | https://github.blog/news-insights/company-news/github-availability-report-march-2023/ |
| 4 | GitHub availability report: June 2026 | other | 0.693 | https://github.blog/news-insights/company-news/github-availability-report-june-2026/ |
| 5 | Denial of Service Attacks | summary | 0.687 | https://github.blog/news-insights/the-library/denial-of-service-attacks/ |

### minilm (sentence-transformers/all-MiniLM-L6-v2)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | GitHub Availability Report: November 2025 | other | 0.516 | https://github.blog/news-insights/company-news/github-availability-report-november-2025/ |
| 2 | GitHub availability report: July 2026 | other | 0.496 | https://github.blog/news-insights/company-news/github-availability-report-july-2026/ |
| 3 | Add-Ons Outage Post-Mortem Result - Mozilla Hacks - the Web developer blog | root_cause | 0.468 | https://web.archive.org/web/20250303152906/https://hacks.mozilla.org/2019/07/add-ons-outage-post-mortem-result/ |
| 4 | Dropbox Tech Blog | impact | 0.427 | https://blogs.dropbox.com/tech/2014/01/outage-post-mortem/ |
| 5 | GitHub Availability Report: May 2021 | other | 0.411 | https://github.blog/news-insights/company-news/github-availability-report-may-2021/ |

## Query: a bad configuration push to the load balancers caused a global outage

### bge (BAAI/bge-small-en-v1.5)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | Global: Experiencing Issue with Cloud networking | other | 0.779 | https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh |
| 2 | Multiple services were experiencing issues in the europe-west2 region. | impact | 0.777 | https://status.cloud.google.com/incidents/Xs2XTHzAVC9YnafnPyzj |
| 3 | Google Compute Engine Incident #17007 | summary | 0.772 | https://status.cloud.google.com/incident/compute/17007 |
| 4 | Google Compute Engine Incident #17007 | summary | 0.770 | https://status.cloud.google.com/incident/compute/17007 |
| 5 | Summary of June 8 outage / Fastly | summary | 0.764 | https://www.fastly.com/blog/summary-of-june-8-outage |

### minilm (sentence-transformers/all-MiniLM-L6-v2)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | Summary of June 8 outage / Fastly | summary | 0.697 | https://www.fastly.com/blog/summary-of-june-8-outage |
| 2 | Outage Post-Mortem: August 25th, 2014 | summary | 0.615 | https://web.archive.org/web/20201020103424/https://stackstatus.net/post/96025967369/outage-post-mortem-august-25th-2014 |
| 3 | Global: Experiencing Issue with Cloud networking | other | 0.614 | https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh |
| 4 | Global: Experiencing Issue with Cloud networking | summary | 0.605 | https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh |
| 5 | Global: Experiencing Issue with Cloud networking | summary | 0.600 | https://status.cloud.google.com/incidents/6PM5mNd43NbMqjCZ5REh |

## Query: disk filled up and the primary database stopped accepting writes

### bge (BAAI/bge-small-en-v1.5)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | What We Learned from the Recent Mandrill Outage / Mailchimp | other | 0.762 | https://mailchimp.com/what-we-learned-from-the-recent-mandrill-outage/ |
| 2 | GitHub Availability Report: August 2021 | other | 0.727 | https://github.blog/news-insights/company-news/github-availability-report-august-2021/ |
| 3 | GitHub Availability Report: September 2023 | other | 0.718 | https://github.blog/news-insights/company-news/github-availability-report-september-2023/ |
| 4 | Incident review: API and Dashboard outage on 10 October 2017 | other | 0.717 | https://gocardless.com/blog/incident-review-api-and-dashboard-outage-on-10th-october/ |
| 5 | Incident 2023-12-04: Data leak and loss in some free tier databases | summary | 0.716 | https://blog.turso.tech/incident-2023-12-04-data-leak-and-loss-in-some-free-tier-databases-7cba5bc7 |

### minilm (sentence-transformers/all-MiniLM-L6-v2)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | Outage report 7 July 2020 - PythonAnywhere News | other | 0.478 | https://blog.pythonanywhere.com/189/ |
| 2 | Incident review: API and Dashboard outage on 10 October 2017 | other | 0.466 | https://gocardless.com/blog/incident-review-api-and-dashboard-outage-on-10th-october/ |
| 3 | GitHub availability report: September 2026 | root_cause | 0.450 | https://github.blog/news-insights/company-news/github-availability-report-september-2026/ |
| 4 | Outage report 7 July 2020 - PythonAnywhere News | other | 0.447 | https://blog.pythonanywhere.com/189/ |
| 5 | GitHub availability report: October 2026 | other | 0.429 | https://github.blog/news-insights/company-news/github-availability-report-october-2026/ |

## Query: BGP route leak made a CDN unreachable for customers

### bge (BAAI/bge-small-en-v1.5)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | Route leak incident on January 22, 2026 | summary | 0.789 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 2 | Route leak incident on January 22, 2026 | other | 0.762 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 3 | Route leak incident on January 22, 2026 | summary | 0.760 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 4 | Route leak incident on January 22, 2026 | summary | 0.747 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 5 | Route leak incident on January 22, 2026 | other | 0.742 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |

### minilm (sentence-transformers/all-MiniLM-L6-v2)

| Rank | Title | Section | Score | URL |
| --- | --- | --- | --- | --- |
| 1 | Route leak incident on January 22, 2026 | other | 0.642 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 2 | Route leak incident on January 22, 2026 | summary | 0.624 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 3 | Route leak incident on January 22, 2026 | other | 0.605 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 4 | Route leak incident on January 22, 2026 | summary | 0.581 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |
| 5 | Route leak incident on January 22, 2026 | remediation | 0.557 | https://blog.cloudflare.com/route-leak-incident-january-22-2026/ |

## Observations (written by hand after the run)

This is a quick qualitative read of the tables above, not a metric. Relevance was judged by reading
titles and checking whether the returned chunk text contains the key terms of the query
(a keyword check, not a labeled judgment). The quantitative comparison is planned for M3.

- Query 1 (split brain): no returned chunk from either model contains "split brain". Both mostly return
  chunks that mention database failover (bge 3 of 5, minilm 4 of 5 contain "failover"). The corpus has
  no obvious split-brain postmortem among the top results, so this query mainly shows what each model
  falls back to.
- Query 2 (expired certificate): the two models share the top two chunks (GitHub availability reports that
  mention certificates and expiry). minilm then surfaces the Mozilla add-ons and Dropbox postmortems, whose
  chunks mention certificates. bge ranks two more GitHub reports and a denial-of-service article; the last
  two of those (the June 2026 report and the article) do not contain the word "certificate".
- Query 3 (bad config push to load balancers): both return plausible network or config incidents (Google
  Cloud, Fastly). Four of bge's five are Google Cloud pages; minilm mixes Fastly, StackExchange and
  Google Cloud.
- Query 4 (disk full, database stopped accepting writes): the models share one document (the GoCardless
  incident review) and otherwise differ; neither produces an obvious exact match from titles alone.
- Query 5 (BGP route leak): both return the same Cloudflare route leak postmortem for all five slots, i.e.
  one document dominates the results. Result diversification (grouping chunks by document) would help
  display and is worth considering for the agent in M2.
- Across the five queries, bge-small returns 11 of 25 chunks from GitHub blog posts and minilm 8 of 25
  (monthly availability reports cover many incident types in one document, which makes them match many
  queries). minilm's top five come from more distinct hosts in queries 1, 2 and 3 (3 vs 1, 3 vs 1, 3 vs 2);
  bge has more in query 4 (4 vs 3). Which behavior is better depends on the gold set and is left to M3.
