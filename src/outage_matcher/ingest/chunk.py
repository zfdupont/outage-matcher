"""Extract main text from postmortem HTML and split it into section-typed chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

MAX_CHARS = 1000  # about 250 tokens; MiniLM truncates at 256 word pieces
MIN_BODY_CHARS = 40  # documents with less body text than this yield no chunks

NOISE_TAGS = ("head", "script", "style", "noscript", "nav", "header", "footer", "aside", "form")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
BLOCK_TAGS = ("p", "li", "pre", "blockquote", "dd", "dt", "td", "th")
# Tags whose text joins the surrounding run of text instead of starting a new paragraph.
INLINE_TAGS = frozenset(
    "a abbr b bdi bdo cite code data del dfn em font i img ins kbd label mark q s samp small "
    "span strong sub sup time tt u var wbr".split()
)
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


def _is_pseudo_heading(node: Tag, text: str) -> bool:
    """A short paragraph that is entirely bold, like <p><strong>Timeline</strong></p>."""
    if node.name != "p" or len(text) > 80 or text.endswith((".", ",", ";")):
        return False
    bold = node.find(["strong", "b"])
    return bold is not None and _clean(bold.get_text(" ")) == text


class _SectionBuilder:
    """Walks the DOM in order. Block tags are paragraphs, containers are recursed into, and
    loose text between them (including <br> separated lines) becomes its own paragraphs."""

    def __init__(self) -> None:
        self.sections: list[Section] = []
        self.current = Section(heading="", section_type="summary")
        self.saw_heading = False
        self._run: list[str] = []

    def _flush_run(self) -> None:
        text = _clean(" ".join(self._run))
        self._run = []
        if text:
            self.current.paragraphs.append(text)

    def _start_section(self, heading: str, from_h1: bool) -> None:
        self.sections.append(self.current)
        section_type = classify_heading(heading)
        if from_h1 and not self.saw_heading and section_type == "other":
            section_type = "summary"  # the title heading introduces the document
        self.current = Section(heading=heading, section_type=section_type)
        self.saw_heading = True

    def walk(self, node: Tag) -> None:
        for child in node.children:
            if isinstance(child, Tag):
                self._visit(child)
            elif isinstance(child, NavigableString) and not isinstance(child, Comment):
                self._run.append(str(child))

    def _visit(self, tag: Tag) -> None:
        if tag.name == "br":
            self._flush_run()
        elif tag.name in HEADING_TAGS:
            self._flush_run()
            text = _clean(tag.get_text(" "))
            if text:
                self._start_section(text, from_h1=tag.name == "h1")
        elif tag.name in BLOCK_TAGS:
            self._flush_run()
            text = _clean(tag.get_text(" "))
            if not text:
                return
            if _is_pseudo_heading(tag, text):
                self._start_section(text, from_h1=False)
            else:
                self.current.paragraphs.append(text)
        elif tag.name in INLINE_TAGS and not tag.find(HEADING_TAGS + BLOCK_TAGS):
            self._run.append(tag.get_text(" "))
        else:
            self._flush_run()
            self.walk(tag)
            self._flush_run()

    def finish(self) -> list[Section]:
        self._flush_run()
        self.sections.append(self.current)
        if not self.saw_heading:
            for section in self.sections:
                section.section_type = "other"
        return [s for s in self.sections if s.paragraphs]


def extract_sections(html: str) -> list[Section]:
    """Group the main content's text under its headings, keeping every non-empty section."""
    soup = BeautifulSoup(html, "lxml")
    main = _find_main(soup)
    for tag in main(NOISE_TAGS):
        tag.decompose()
    builder = _SectionBuilder()
    builder.walk(main)
    sections = builder.finish()
    if sum(len(p) for s in sections for p in s.paragraphs) < MIN_BODY_CHARS:
        return []
    return sections


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
        # The heading is prepended to every chunk, so budget for it to keep chunks under the cap.
        prefix = f"{section.heading}\n" if section.heading else ""
        body_limit = max(max_chars - len(prefix), max_chars // 2)
        for body in _pack(section.paragraphs, body_limit):
            chunks.append(
                Chunk(ord=len(chunks), section_type=section.section_type, text=prefix + body)
            )
    return chunks


def chunk_html(html: str, max_chars: int = MAX_CHARS) -> list[Chunk]:
    """Chunk a postmortem page. Returns [] when no usable text is found."""
    return chunk_sections(extract_sections(html), max_chars)
