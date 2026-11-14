"""Collect public postmortems for local indexing.

Source list: the community list danluu/post-mortems plus a few provider incident
report indexes. Raw HTML goes to data/raw/ (git-ignored); only the manifest is
committed. See docs/sources.md for the per-source terms check.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import warnings
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

USER_AGENT = "outage-matcher-research/0.1 (local indexing of public postmortems)"
DANLUU_URL = "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md"
GITHUB_TAG_URL = "https://github.blog/tag/github-availability-report/"
CLOUDFLARE_TAG_URL = "https://blog.cloudflare.com/tag/post-mortem/"
GCP_SUMMARY_URL = "https://status.cloud.google.com/summary"

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = DATA_DIR / "manifest.jsonl"
FAILURES_PATH = DATA_DIR / "collect_failures.jsonl"

MIN_TEXT_CHARS = 1500
MAX_BYTES = 3_000_000
DEFAULT_MAX_DOCS = 300
DEFAULT_DELAY = 1.0
ARCHIVE_DELAY = 2.0

# Hosts never fetched, with the reason recorded in docs/sources.md.
DENY_HOSTS: dict[str, str] = {
    "aws.amazon.com": "AWS Site Terms prohibit data mining, robots and downloading",
    "medium.com": "Medium terms restrict automated access",
    "twitter.com": "social platform, not a postmortem document",
    "x.com": "social platform, not a postmortem document",
    "youtube.com": "video",
    "www.youtube.com": "video",
    "linkedin.com": "signed-in platform",
    "www.reddit.com": "user content with platform terms against scraping",
    "github.com": "user repositories with mixed licenses",
    "en.wikipedia.org": "encyclopedia article, not a primary postmortem",
    # Employer data is out of scope for this project.
    "facebook.com": "employer data excluded",
    "www.facebook.com": "employer data excluded",
    "engineering.fb.com": "employer data excluded",
    "code.facebook.com": "employer data excluded",
    "fb.com": "employer data excluded",
    "meta.com": "employer data excluded",
    "about.meta.com": "employer data excluded",
    "engineering.meta.com": "employer data excluded",
}
DENY_LABELS = {"facebook", "meta", "instagram", "whatsapp"}

SYSTEM_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "database": (
        "database",
        "postgres",
        "mysql",
        "mongodb",
        "replication",
        "replica",
        "failover",
        "primary node",
        "dynamodb",
        "cassandra",
        "redis",
        "sql",
        "schema",
        "split brain",
    ),
    "network": (
        "network",
        "dns",
        "bgp",
        "routing",
        "router",
        "load balancer",
        "packet",
        "latency",
        "cdn",
        "firewall",
        "vpn",
        "tls",
        "certificate",
        "connectivity",
    ),
    "storage": (
        "storage",
        "disk",
        "s3",
        "filesystem",
        "file system",
        "volume",
        "snapshot",
        "backup",
        "object store",
    ),
    "compute": (
        "kubernetes",
        "container",
        "cluster",
        "scheduler",
        "autoscal",
        "virtual machine",
        "cpu",
        "memory",
        "deploy",
        "rollout",
        "instance",
    ),
    "messaging": ("queue", "kafka", "pubsub", "message broker", "rabbitmq", "stream"),
    "identity": ("authentication", "oauth", "login", "sso", "identity", "token", "credential"),
    "hardware": ("power", "datacenter", "data center", "generator", "cooling", "hardware", "ups"),
}
DEFAULT_SYSTEM_TYPE = "other"


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    label: str = ""


@dataclass(frozen=True)
class ManifestEntry:
    doc_id: str
    url: str
    title: str
    source: str
    fetched_date: str
    system_type: str


def doc_id_for(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def original_url(url: str) -> str:
    """Return the underlying URL for a web.archive.org snapshot URL."""
    match = re.match(r"https?://web\.archive\.org/web/\d+[a-z_]*/(.+)", url)
    if not match:
        return url
    inner = match.group(1)
    return inner if inner.startswith("http") else "https://" + inner


def fetch_url_for(url: str) -> str:
    """Use the raw (id_) variant of archive snapshots so no toolbar HTML is injected."""
    return re.sub(r"(https?://web\.archive\.org/web/\d+)/", r"\1id_/", url, count=1)


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def source_for(url: str) -> str:
    host = host_of(original_url(url))
    if host == "blog.cloudflare.com":
        return "cloudflare"
    if host == "github.blog":
        return "github"
    if host == "status.cloud.google.com":
        return "gcp"
    return "community"


def deny_reason(url: str, label: str = "") -> str | None:
    if label.strip().lower() in DENY_LABELS:
        return "employer data excluded"
    host = host_of(original_url(url))
    for denied, reason in DENY_HOSTS.items():
        if host == denied or host.endswith("." + denied):
            return reason
    if urlparse(original_url(url)).path.lower().endswith(".pdf"):
        return "not HTML"
    return None


def parse_danluu(markdown: str) -> list[Candidate]:
    """Extract (company, url) pairs from the list. Only the URL and company name are kept."""
    out: list[Candidate] = []
    for line in markdown.splitlines():
        match = re.match(r"^\[([^\]]+)\]\((https?://[^)\s]+)\)", line.strip())
        if match:
            label, url = match.groups()
            out.append(Candidate(url=urldefrag(url)[0], source=source_for(url), label=label))
    return out


def extract_links(html: str, base: str, pattern: str) -> list[str]:
    """Absolute links in an index page whose URL matches the regex, in page order."""
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        absolute = urldefrag(urljoin(base, a["href"]))[0]
        if re.search(pattern, absolute):
            seen.setdefault(absolute, None)
    return list(seen)


GENERIC_TITLE = re.compile(r"^(incident details|google cloud status dashboard)\b", re.I)


def html_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title = ""
    for finder in (
        lambda: soup.find("meta", property="og:title"),
        lambda: soup.find("title"),
        lambda: soup.find("h1"),
    ):
        node = finder()
        if node is None:
            continue
        text = node.get("content") if node.name == "meta" else node.get_text()
        title = re.sub(r"\s+", " ", text or "").strip()
        if title:
            break
    title = re.sub(r"\s*[\u2013\u2014]\s*", " - ", title)  # keep stored titles ASCII-dash only
    if GENERIC_TITLE.match(title):
        # Google Cloud incident pages share one page title; use the incident heading instead.
        headings = [
            re.sub(r"\s+", " ", h.get_text(" ")).strip() for h in soup.find_all(["h1", "h2"])
        ]
        specific = [h for h in headings if re.search(r"incident #|experiencing|issues", h, re.I)]
        h2s = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
        title = (specific or [h for h in h2s if h and not h.startswith("#")] or [title])[0]
    return title


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["head", "script", "style", "noscript", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def classify_system_type(title: str, text: str) -> str:
    """Heuristic keyword label for the affected system type. Not ground truth."""
    body = (title + " ") * 3 + text[:4000]
    body = body.lower()
    scores = {
        label: sum(len(re.findall(r"\b" + re.escape(k), body)) for k in keywords)
        for label, keywords in SYSTEM_TYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 3 else DEFAULT_SYSTEM_TYPE


def blocks_ai_input(html: str) -> bool:
    """True if page meta robots says noindex/noai (we index locally, so honor both)."""
    soup = BeautifulSoup(html, "lxml")
    for meta in soup.find_all("meta", attrs={"name": re.compile("^(robots|googlebot)$", re.I)}):
        content = (meta.get("content") or "").lower()
        if "noindex" in content or "noai" in content:
            return True
    return False


class RobotsUnavailable(Exception):
    pass


class Fetcher:
    """Polite HTTP client: robots.txt, per-host delay, generic User-Agent."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        delay: float = DEFAULT_DELAY,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
            follow_redirects=True,
        )
        self.delay = delay
        self._sleep = sleep
        self._clock = clock
        self._last: dict[str, float] = {}
        self._robots: dict[str, tuple[RobotFileParser | None, bool]] = {}

    def _wait(self, host: str) -> None:
        gap = ARCHIVE_DELAY if host == "web.archive.org" else self.delay
        last = self._last.get(host)
        if last is not None:
            remaining = gap - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()

    def get(self, url: str) -> httpx.Response:
        self._wait(host_of(url))
        return self.client.get(url, headers={"User-Agent": USER_AGENT})

    def _load_robots(self, url: str) -> tuple[RobotFileParser | None, bool]:
        """Return (parser or None when robots.txt is absent, content-signal blocks ai-input)."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        parser: RobotFileParser | None = RobotFileParser()
        signal_blocks = False
        try:
            resp = self.get(robots_url)
        except httpx.HTTPError as exc:
            raise RobotsUnavailable(f"robots.txt fetch failed: {exc.__class__.__name__}") from exc
        if resp.status_code >= 500:
            raise RobotsUnavailable(f"robots.txt returned {resp.status_code}")
        if resp.status_code >= 400 or "text" not in resp.headers.get("content-type", "text"):
            parser = None
        else:
            assert parser is not None
            parser.parse(resp.text.splitlines())
            signal = re.search(r"(?im)^\s*content-signal:\s*(.*)$", resp.text)
            signal_blocks = bool(signal and re.search(r"ai-input\s*=\s*no", signal.group(1)))
        self._robots[origin] = (parser, signal_blocks)
        return parser, signal_blocks

    def allowed(self, url: str) -> tuple[bool, str]:
        try:
            parser, signal_blocks = self._load_robots(url)
        except RobotsUnavailable as exc:
            return False, str(exc)
        if signal_blocks:
            return False, "content-signal ai-input=no"
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            return False, "disallowed by robots.txt"
        return True, ""


def collect_candidates(fetcher: Fetcher, *, seed: int = 0) -> list[Candidate]:
    """Provider reports first, then the community list in a fixed shuffled order."""
    out: list[Candidate] = []

    def index_links(url: str, pattern: str, source: str, pages: int = 1) -> None:
        for n in range(1, pages + 1):
            page_url = url if n == 1 else f"{url}page/{n}/"
            try:
                resp = fetcher.get(page_url)
            except httpx.HTTPError:
                break
            if resp.status_code != 200:
                break
            links = extract_links(resp.text, page_url, pattern)
            if not links:
                break
            out.extend(Candidate(link, source) for link in links)

    index_links(
        GITHUB_TAG_URL,
        r"github\.blog/.*github-availability-report-[a-z]+-\d{4}/?$",
        "github",
        pages=12,
    )
    index_links(
        CLOUDFLARE_TAG_URL,
        r"^https://blog\.cloudflare\.com/(?!tag/|rss|[a-z]{2}-[a-z]{2}/)[a-z0-9-]+/?$",
        "cloudflare",
    )
    index_links(GCP_SUMMARY_URL, r"status\.cloud\.google\.com/incidents/[A-Za-z0-9]+$", "gcp")

    resp = fetcher.get(DANLUU_URL)
    resp.raise_for_status()
    community = parse_danluu(resp.text)
    random.Random(seed).shuffle(community)
    out.extend(community)
    return dedupe(out)


def dedupe(candidates: Iterable[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for cand in candidates:
        key = original_url(cand.url).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def fetch_one(
    fetcher: Fetcher, cand: Candidate, raw_dir: Path, today: date
) -> tuple[ManifestEntry | None, str]:
    """Fetch and validate one candidate. Returns (entry, "") or (None, failure reason)."""
    reason = deny_reason(cand.url, cand.label)
    if reason:
        return None, f"denied: {reason}"
    doc_id = doc_id_for(cand.url)
    raw_path = raw_dir / f"{doc_id}.html"
    fetch_url = fetch_url_for(cand.url)
    ok, why = fetcher.allowed(fetch_url)
    if not ok:
        return None, why
    try:
        resp = fetcher.get(fetch_url)
    except httpx.HTTPError as exc:
        return None, f"fetch error: {exc.__class__.__name__}"
    if resp.status_code != 200:
        return None, f"http {resp.status_code}"
    if "html" not in resp.headers.get("content-type", "").lower():
        return None, "not html"
    if len(resp.content) > MAX_BYTES:
        return None, "too large"
    html = resp.text
    if blocks_ai_input(html):
        return None, "page meta robots forbids indexing"
    text = visible_text(html)
    if len(text) < MIN_TEXT_CHARS:
        return None, f"too little text ({len(text)} chars)"
    title = html_title(html) or cand.label or cand.url
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(html, encoding="utf-8")
    entry = ManifestEntry(
        doc_id=doc_id,
        url=cand.url,
        title=title,
        source=cand.source,
        fetched_date=today.isoformat(),
        system_type=classify_system_type(title, text),
    )
    return entry, ""


def read_manifest(path: Path = MANIFEST_PATH) -> list[ManifestEntry]:
    if not path.exists():
        return []
    return [
        ManifestEntry(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def read_failures(path: Path = FAILURES_PATH) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_manifest(entries: Iterable[ManifestEntry], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(entries, key=lambda e: (e.source, e.url))
    path.write_text(
        "".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in ordered),
        encoding="utf-8",
    )


def refreshed(entry: ManifestEntry, raw_dir: Path) -> ManifestEntry:
    """Recompute title and system type from the stored page so heuristic fixes apply on resume."""
    html = (raw_dir / f"{entry.doc_id}.html").read_text(encoding="utf-8", errors="replace")
    title = html_title(html) or entry.title
    system_type = classify_system_type(title, visible_text(html))
    return replace(entry, title=title, system_type=system_type)


def collect(
    *,
    max_docs: int = DEFAULT_MAX_DOCS,
    fetcher: Fetcher | None = None,
    data_dir: Path = DATA_DIR,
    today: date | None = None,
    log: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[ManifestEntry], list[dict[str, str]]]:
    """Fetch candidates until max_docs documents are stored. Resumes from the manifest."""
    fetcher = fetcher or Fetcher()
    today = today or date.today()
    raw_dir = data_dir / "raw"
    manifest_path = data_dir / "manifest.jsonl"
    existing = {
        e.url: refreshed(e, raw_dir)
        for e in read_manifest(manifest_path)
        if (raw_dir / f"{e.doc_id}.html").exists()
    }
    entries = dict(existing)
    failures: list[dict[str, str]] = []
    for cand in collect_candidates(fetcher):
        if len(entries) >= max_docs:
            break
        if cand.url in entries:
            continue
        entry, reason = fetch_one(fetcher, cand, raw_dir, today)
        if entry is None:
            failures.append({"url": cand.url, "source": cand.source, "reason": reason})
            log(f"skip {cand.url}: {reason}")
            continue
        entries[entry.url] = entry
        log(f"ok {len(entries)}/{max_docs} {cand.source} {entry.title[:60]}")
    write_manifest(entries.values(), manifest_path)
    failures_path = data_dir / "collect_failures.jsonl"
    failures_path.write_text(
        "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in failures), encoding="utf-8"
    )
    return list(entries.values()), failures
