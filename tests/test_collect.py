import json
from datetime import date

import httpx

from outage_matcher.ingest import collect

LONG_BODY = "The database primary failed and replication lagged during failover. " * 40


def page(title: str, body: str = LONG_BODY, head: str = "") -> str:
    return f"<html><head><title>{title}</title>{head}</head><body><p>{body}</p></body></html>"


def make_fetcher(routes: dict[str, httpx.Response | str], calls: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
            assert request.headers["user-agent"] == collect.USER_AGENT
        value = routes.get(url)
        if value is None:
            return httpx.Response(404, text="not found")
        if isinstance(value, str):
            return httpx.Response(200, text=value, headers={"content-type": "text/html"})
        return value

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return collect.Fetcher(client, sleep=lambda _s: None)


def test_parse_danluu_keeps_url_and_label_only():
    md = (
        "## Config Errors\n\n"
        "[Allegro](https://allegro.tech/2018/08/pm.html). Went down after a spike.\n\n"
        "[Cloudflare](https://web.archive.org/web/2021/https://blog.cloudflare.com/x/). Bad.\n"
        "not a link line\n"
    )
    cands = collect.parse_danluu(md)
    assert [(c.label, c.url, c.source) for c in cands] == [
        ("Allegro", "https://allegro.tech/2018/08/pm.html", "community"),
        (
            "Cloudflare",
            "https://web.archive.org/web/2021/https://blog.cloudflare.com/x/",
            "cloudflare",
        ),
    ]


def test_archive_url_helpers():
    url = "https://web.archive.org/web/20211006135542/https://blog.cloudflare.com/a/"
    assert collect.original_url(url) == "https://blog.cloudflare.com/a/"
    assert collect.fetch_url_for(url) == (
        "https://web.archive.org/web/20211006135542id_/https://blog.cloudflare.com/a/"
    )
    assert collect.original_url("https://example.com/x") == "https://example.com/x"


def test_deny_reason_covers_aws_employer_and_pdf():
    assert "AWS" in collect.deny_reason("https://aws.amazon.com/message/74876-2/")
    assert collect.deny_reason("https://engineering.fb.com/2021/10/outage/")
    assert collect.deny_reason("https://example.com/post", label="Facebook")
    assert collect.deny_reason("https://example.com/report.pdf")
    assert collect.deny_reason("https://web.archive.org/web/2020/https://aws.amazon.com/message/1/")
    assert collect.deny_reason("https://blog.cloudflare.com/outage/") is None


def test_classify_system_type_and_fallback():
    assert collect.classify_system_type("Postgres failover", LONG_BODY) == "database"
    assert collect.classify_system_type("BGP leak", "dns and routing and network " * 3) == "network"
    assert collect.classify_system_type("Hello", "nothing relevant here") == "other"


def test_title_and_visible_text():
    html = (
        "<html><head><title> A  Title </title></head><body><nav>menu</nav><p>Body</p></body></html>"
    )
    assert collect.html_title(html) == "A Title"
    assert collect.visible_text(html) == "Body"
    og = '<head><meta property="og:title" content="OG"><title>T</title></head>'
    assert collect.html_title(f"<html>{og}<body></body></html>") == "OG"


def test_robots_disallow_content_signal_and_missing_file():
    robots = {
        "https://a.test/robots.txt": "User-agent: *\nDisallow: /private/\n",
        "https://b.test/robots.txt": "User-agent: *\nAllow: /\nContent-Signal: ai-input=no\n",
    }
    fetcher = make_fetcher(robots)
    assert fetcher.allowed("https://a.test/private/x") == (False, "disallowed by robots.txt")
    assert fetcher.allowed("https://a.test/public/x")[0] is True
    assert fetcher.allowed("https://b.test/x") == (False, "content-signal ai-input=no")
    assert fetcher.allowed("https://c.test/x")[0] is True  # robots.txt 404 means allowed


def test_robots_server_error_is_conservative():
    fetcher = make_fetcher({"https://d.test/robots.txt": httpx.Response(503)})
    ok, why = fetcher.allowed("https://d.test/x")
    assert ok is False and "503" in why


def test_rate_limit_waits_per_host():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    fetcher = collect.Fetcher(client, delay=1.0, sleep=sleep, clock=lambda: now[0])
    fetcher.get("https://a.test/1")
    fetcher.get("https://b.test/1")  # different host: no wait
    assert sleeps == []
    fetcher.get("https://a.test/2")
    assert sleeps == [1.0]


def test_fetch_one_success_writes_raw_and_entry(tmp_path):
    url = "https://example.test/pm"
    fetcher = make_fetcher({url: page("Primary failover outage")})
    entry, reason = collect.fetch_one(
        fetcher, collect.Candidate(url, "community", "Ex"), tmp_path / "raw", date(2026, 11, 13)
    )
    assert reason == ""
    assert entry.title == "Primary failover outage"
    assert entry.system_type == "database"
    assert entry.fetched_date == "2026-11-13"
    assert (tmp_path / "raw" / f"{entry.doc_id}.html").exists()


def test_fetch_one_failure_reasons(tmp_path):
    routes = {
        "https://short.test/p": page("Short", "tiny"),
        "https://noai.test/p": page("T", head='<meta name="robots" content="noai">'),
        "https://pdf.test/p": httpx.Response(
            200, content=b"x", headers={"content-type": "application/pdf"}
        ),
        "https://gone.test/p": httpx.Response(410),
        "https://blocked.test/robots.txt": "User-agent: *\nDisallow: /\n",
        "https://blocked.test/p": page("T"),
    }
    fetcher = make_fetcher(routes)
    today = date(2026, 11, 13)

    def reason(url: str) -> str:
        entry, why = collect.fetch_one(
            fetcher, collect.Candidate(url, "community"), tmp_path, today
        )
        assert entry is None
        return why

    assert reason("https://short.test/p").startswith("too little text")
    assert "meta robots" in reason("https://noai.test/p")
    assert reason("https://pdf.test/p") == "not html"
    assert reason("https://gone.test/p") == "http 410"
    assert reason("https://blocked.test/p") == "disallowed by robots.txt"
    assert reason("https://aws.amazon.com/message/1/").startswith("denied")
    assert not list(tmp_path.glob("*.html"))


def test_collect_end_to_end_with_manifest(tmp_path):
    danluu = (
        "[Acme](https://acme.test/pm1). x\n"
        "[Beta](https://beta.test/pm2). y\n"
        "[Amazon](https://aws.amazon.com/message/1/). z\n"
        "[Cloudflare](https://blog.cloudflare.com/dup-post/). dup\n"
    )
    gh_index = '<a href="https://github.blog/news-insights/company-news/github-availability-report-may-2026/">r</a>'
    cf_index = '<a href="/dup-post/">p</a><a href="/tag/other/">t</a><a href="/de-de/">l</a>'
    routes = {
        collect.DANLUU_URL: danluu,
        collect.GITHUB_TAG_URL: gh_index,
        collect.CLOUDFLARE_TAG_URL: cf_index,
        "https://github.blog/news-insights/company-news/github-availability-report-may-2026/": page(
            "GitHub availability report: May 2026"
        ),
        "https://blog.cloudflare.com/dup-post/": page("Cloudflare postmortem DNS routing network"),
        "https://acme.test/pm1": page("Acme outage"),
        "https://beta.test/pm2": page("Beta", "tiny"),
    }
    calls: list[str] = []
    fetcher = make_fetcher(routes, calls)
    data = tmp_path / "data"
    entries, failures = collect.collect(fetcher=fetcher, data_dir=data, today=date(2026, 11, 13))

    assert sorted(e.source for e in entries) == ["cloudflare", "community", "github"]
    assert not any("aws.amazon.com" in c for c in calls)
    assert {f["url"]: f["reason"].split(" (")[0] for f in failures} == {
        "https://beta.test/pm2": "too little text",
        "https://aws.amazon.com/message/1/": "denied: AWS Site Terms prohibit data mining, robots "
        "and downloading",
    }
    rows = [json.loads(line) for line in (data / "manifest.jsonl").read_text().splitlines()]
    assert set(rows[0]) == {"doc_id", "url", "title", "source", "fetched_date", "system_type"}
    assert len(rows) == 3
    assert len(list((data / "raw").glob("*.html"))) == 3

    # second run resumes from the manifest and does not refetch stored documents
    calls.clear()
    collect.collect(fetcher=make_fetcher(routes, calls), data_dir=data, today=date(2026, 11, 14))
    assert "https://acme.test/pm1" not in calls
    assert len(collect.read_manifest(data / "manifest.jsonl")) == 3


def test_collect_stops_at_max_docs(tmp_path):
    danluu = "".join(f"[C{i}](https://h{i}.test/p). x\n" for i in range(5))
    routes = {collect.DANLUU_URL: danluu} | {
        f"https://h{i}.test/p": page(f"T{i}") for i in range(5)
    }
    entries, _ = collect.collect(
        max_docs=2, fetcher=make_fetcher(routes), data_dir=tmp_path / "d", today=date(2026, 1, 1)
    )
    assert len(entries) == 2


def test_generic_google_cloud_titles_use_incident_heading():
    html = (
        "<html><head><title>Incident details | Google Cloud Service Health</title></head>"
        "<body><h1>Service Health</h1><h2>We are experiencing Networking issues</h2></body></html>"
    )
    assert collect.html_title(html) == "We are experiencing Networking issues"
    old = (
        "<html><head><title>Google Cloud Status Dashboard</title></head><body>"
        "<h1>Google Cloud Status Dashboard</h1><h1>Google Compute Engine Incident #15056</h1>"
        "</body></html>"
    )
    assert collect.html_title(old) == "Google Compute Engine Incident #15056"


def test_refreshed_recomputes_title_from_raw(tmp_path):
    entry = collect.ManifestEntry(
        "abc", "https://x.test/p", "old", "community", "2026-11-13", "other"
    )
    (tmp_path / "abc.html").write_text(page("New title"))
    out = collect.refreshed(entry, tmp_path)
    assert (out.title, out.system_type, out.fetched_date) == ("New title", "database", "2026-11-13")


def test_title_dashes_are_normalized():
    html = "<html><head><title>Outage \u2013 post\u2014mortem</title></head><body></body></html>"
    assert collect.html_title(html) == "Outage - post - mortem"
