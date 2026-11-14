# Sources and terms checks

Checked 2026-11-13. Use of every source below: local indexing only. Raw HTML is stored
under `data/raw/` (git-ignored) and is never committed or redistributed. The committed
`data/manifest.jsonl` holds only the URL, page title, source label, fetch date and a
heuristic system-type label. Answers cite the original URL.

Fetching rules (implemented in `src/outage_matcher/ingest/collect.py`):

- Generic User-Agent `outage-matcher-research/0.1 (local indexing of public postmortems)`.
- `robots.txt` is fetched per origin and honored. A 5xx or unreachable `robots.txt` skips the host.
  A `Content-Signal` line with `ai-input=no` skips the host. A page-level meta robots
  `noindex` or `noai` skips the page.
- At most one request per second per host (two seconds for web.archive.org).
- Only `text/html` responses, at most 3 MB each. Pages with under 1500 characters of visible text are dropped.
- Hosts on the deny list in `collect.py` are never fetched.

## Used

| Source | What is fetched | Terms check | Decision |
| --- | --- | --- | --- |
| danluu/post-mortems README (raw.githubusercontent.com) | Only the list of links and company names. The README descriptions are not stored. | The repository has no license file (GitHub API reports no license). A list of public URLs is used for discovery only. | Allowed as a link list. Linked pages are subject to their own checks below. |
| Cloudflare blog (blog.cloudflare.com) | Postmortem posts from the `post-mortem` tag page, plus any linked from the community list. | `robots.txt` allows all with `Content-Signal: ai-train=yes, search=yes, ai-input=yes`. Website terms section 8 restricts bots used for AI model training unless robots.txt allows; this project does retrieval indexing, not training, and the signals allow it. | Allowed. |
| GitHub blog availability reports (github.blog) | Monthly "GitHub availability report" posts from the tag pages. | `robots.txt` allows all (`Disallow:` empty). No license is stated on the posts; copyright stays with GitHub. | Allowed for local indexing with citation. No redistribution of text. |
| Google Cloud Service Health (status.cloud.google.com) | Incident pages linked from the `/summary` page. | `robots.txt` allows all. Google Terms of Service prohibit automated access that violates robots.txt, which this does not. | Allowed for local indexing with citation. |
| Other company blogs and status pages from the community list | One page per URL. | Terms are not reviewed host by host (hundreds of hosts). Mitigation: per-host `robots.txt`, content-signal and meta robots checks as above, one request per page, no redistribution, URL citation. Hosts with known restrictions are on the deny list. | Allowed for local indexing under the fetching rules above. A host owner can be added to the deny list on request. |
| web.archive.org snapshots (for dead or moved posts in the community list) | The raw (`id_`) snapshot of the same URL. | `robots.txt` on web.archive.org returns 404 (no restrictions). The Archive terms page is script-rendered and could not be read automatically, so it is not relied on; snapshots are third-party content and are treated under the same policy as the "other company blogs" row, rate limited to one request per two seconds. Denied hosts are checked against the original URL, not the snapshot host. | Allowed under the fetching rules. The manifest keeps the snapshot URL as the citation. |

## Not used

| Source | Why |
| --- | --- |
| AWS service event summaries (aws.amazon.com/message/...) | AWS Site Terms (aws.amazon.com/terms) license the site for personal use only and exclude "data mining, robots, or similar data gathering and extraction tools" and downloading. Skipped, including when linked from the community list. |
| Azure post incident reviews (azure.status.microsoft) | `robots.txt` is absent, but the history page only exposes about 90 days and fills older entries through a script-driven endpoint with no stable per-incident URL. Not worth scraping around; revisit if a stable PIR archive appears. |
| medium.com, github.com repositories, Wikipedia, Reddit, social platforms, PDFs | Platform terms against automated access, mixed user licenses, or not a primary postmortem document. |
| Meta, Facebook and other employer data | Excluded by project rule. Hosts `facebook.com`, `fb.com`, `meta.com` (and engineering subdomains) are on the deny list, as are list entries whose company label is Facebook or Meta. |
