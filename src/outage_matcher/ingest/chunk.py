"""Extract main text from postmortem HTML and split it into section-typed chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

MAX_CHARS = 1000  # about 250 tokens; MiniLM truncates at 256 word pieces
MIN_BODY_CHARS = 40  # sections with less body text than this are dropped

NOISE_TAGS = ("head", "script", "style", "noscript", "nav", "header", "footer", "aside", "form")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BLOCK_TAGS = ("p", "li", "pre", "blockquote", "dd", "dt", "td", "th")
MAIN_SELECTORS = (
    "article",
    "main",
    "[role=main]",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".post-body",
    "#content",
)

SECTION_TYPES = ("summary", "timeline", "root_cause", "impact", "remediation", "other")

# Order matters: the first matching rule wins.
SECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("root_cause", re.compile(r"root cause|cause|why |what went wrong|trigger|contributing", re.I)),
    (
        "remediation",
        re.compile(
            r"remediat|resolution|resolv|fix|mitigat|lessons|action item|next step|prevent"
            r"|follow[- ]?up|what we.?re doing|corrective|improvement|recovery",
            re.I,
        ),
    ),
    ("timeline", re.compile(r"timeline|chronolog|sequence of events|events|detection", re.I)),
    ("impact", re.compile(r"impact|customer|affected|scope|effect|consequence", re.I)),
    (
        "summary",
        re.compile(r"summary|overview|tl;?dr|what happened|introduction|background|incident", re.I),
    ),
)


@dataclass(frozen=True)
class Chunk:
    ord: int
    section_type: str
    text: str


@dataclass
class Section:
    heading: str
    section_type: str
    paragraphs: list[str] = field(default_factory=list)


def classify_heading(heading: str) -> str:
    for section_type, pattern in SECTION_RULES:
        if pattern.search(heading):
            return section_type
    return "other"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _find_main(soup: BeautifulSoup) -> Tag:
    """The largest content container. Pages often hold several <article> cards, with the
    post body in <main> or a content div, so compare all candidates by text length."""
    candidates = [node for selector in MAIN_SELECTORS for node in soup.select(selector)]
    if candidates:
        best = max(candidates, key=lambda n: len(_clean(n.get_text(" "))))
        if len(_clean(best.get_text(" "))) >= 500:
            return best
    return soup.body or soup


def _has_block_ancestor(node: Tag, root: Tag) -> bool:
    for parent in node.parents:
        if parent is root:
            return False
        if parent.name in BLOCK_TAGS:
            return True
    return False


def _is_pseudo_heading(node: Tag, text: str) -> bool:
    """A short paragraph that is entirely bold, like <p><strong>Timeline</strong></p>."""
    if node.name != "p" or len(text) > 80 or text.endswith((".", ",", ";")):
        return False
    bold = node.find(["strong", "b"])
    return bold is not None and _clean(bold.get_text(" ")) == text


def extract_sections(html: str) -> list[Section]:
    """Walk the main content in document order and group paragraphs under headings."""
    soup = BeautifulSoup(html, "lxml")
    main = _find_main(soup)
    for tag in main(NOISE_TAGS):
        tag.decompose()

    sections: list[Section] = []
    current = Section(heading="", section_type="summary")
    saw_heading = False
    block_chars = 0
    for node in main.find_all(HEADING_TAGS + BLOCK_TAGS):
        if node.name not in HEADING_TAGS and _has_block_ancestor(node, main):
            continue
        text = _clean(node.get_text(" "))
        if not text:
            continue
        if node.name in HEADING_TAGS or _is_pseudo_heading(node, text):
            sections.append(current)
            section_type = classify_heading(text)
            if node.name == "h1" and not saw_heading and section_type == "other":
                section_type = "summary"  # the title heading introduces the document
            current = Section(heading=text, section_type=section_type)
            saw_heading = True
        else:
            current.paragraphs.append(text)
            block_chars += len(text)
    sections.append(current)

    full_text_chars = len(_clean(main.get_text(" ")))
    if block_chars < 0.5 * full_text_chars:
        # Text is not wrapped in block tags (for example <br> separated); use raw lines.
        lines = [_clean(line) for line in main.get_text("\n").splitlines()]
        sections = [Section("", "other", [line for line in lines if line])]
        saw_heading = False

    if not saw_heading:
        for section in sections:
            section.section_type = "other"
    return [s for s in sections if sum(len(p) for p in s.paragraphs) >= MIN_BODY_CHARS]


def _split_long(text: str, limit: int) -> list[str]:
    """Split one oversized paragraph on sentence boundaries, then hard-wrap on words."""
    pieces: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if buf and len(buf) + 1 + len(sentence) > limit:
            pieces.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def _pack(paragraphs: list[str], limit: int) -> list[str]:
    units: list[str] = []
    for paragraph in paragraphs:
        units.extend(_split_long(paragraph, limit) if len(paragraph) > limit else [paragraph])
    packed: list[str] = []
    buf = ""
    for unit in units:
        if buf and len(buf) + 1 + len(unit) > limit:
            packed.append(buf)
            buf = unit
        else:
            buf = f"{buf}\n{unit}" if buf else unit
    if buf:
        packed.append(buf)
    return packed


def chunk_sections(sections: list[Section], max_chars: int = MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        for body in _pack(section.paragraphs, max_chars):
            text = f"{section.heading}\n{body}" if section.heading else body
            chunks.append(Chunk(ord=len(chunks), section_type=section.section_type, text=text))
    return chunks


def chunk_html(html: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """Chunk a postmortem page. Returns [] when no usable text is found."""
    return chunk_sections(extract_sections(html), max_chars)
