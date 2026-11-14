from outage_matcher.ingest import chunk

SECTIONED = """
<html><head><title>Postmortem</title></head><body>
<nav>Home About Pricing</nav>
<article>
<h1>Database outage</h1>
<p>On Tuesday our primary database lost its leader and the cluster stopped serving writes.</p>
<h2>Impact</h2>
<p>Customers could not save changes for 47 minutes and about half of API calls failed.</p>
<h2>Timeline</h2>
<ul><li>10:02 alert fired for write errors</li><li>10:20 on-call promoted a replica</li></ul>
<h2>Root cause</h2>
<p>A network partition caused two nodes to both believe they were the primary (split brain).</p>
<h3>Remediation and follow-up</h3>
<p>We added fencing to the failover script and a test that partitions the leader.</p>
<h2>Acknowledgements</h2>
<p>Thanks to everyone on the incident call who helped us get things back to normal.</p>
</article>
<footer>Copyright</footer>
</body></html>
"""

NO_HEADINGS = (
    "<html><body><div><p>"
    + " ".join(f"Sentence number {i} describes what happened during the outage." for i in range(80))
    + "</p></div></body></html>"
)


def test_sections_are_typed_and_noise_is_dropped():
    chunks = chunk.chunk_html(SECTIONED)
    by_type = {c.section_type: c.text for c in chunks}
    assert set(by_type) == {"summary", "impact", "timeline", "root_cause", "remediation", "other"}
    assert "split brain" in by_type["root_cause"]
    assert by_type["root_cause"].startswith("Root cause\n")
    assert "promoted a replica" in by_type["timeline"]
    assert "fencing" in by_type["remediation"]
    assert not any("Pricing" in c.text or "Copyright" in c.text for c in chunks)
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_intro_before_first_heading_is_summary():
    html = (
        "<html><body><article><p>" + "Intro text about the outage. " * 25 + "</p>"
        "<h2>Root cause</h2><p>" + "A bad deploy took the service down. " * 5 + "</p></article>"
        "</body></html>"
    )
    chunks = chunk.chunk_html(html)
    assert chunks[0].section_type == "summary"
    assert chunks[1].section_type == "root_cause"


def test_headingless_document_falls_back_to_size_capped_chunks():
    chunks = chunk.chunk_html(NO_HEADINGS, max_chars=500)
    assert len(chunks) > 3
    assert all(len(c.text) <= 500 for c in chunks)
    assert {c.section_type for c in chunks} == {"other"}
    joined = " ".join(c.text for c in chunks)
    assert "Sentence number 0 " in joined and "Sentence number 79 " in joined


def test_oversized_paragraph_without_sentence_breaks_is_hard_wrapped():
    html = f"<html><body><p>{'word ' * 600}</p></body></html>"
    chunks = chunk.chunk_html(html, max_chars=300)
    assert all(len(c.text) <= 300 for c in chunks)
    assert sum(c.text.count("word") for c in chunks) == 600


def test_bold_only_paragraph_acts_as_heading():
    html = (
        "<html><body><article>"
        "<p>" + "Preamble sentence about the incident. " * 15 + "</p>"
        "<p><strong>Root Cause</strong></p>"
        "<p>" + "The certificate expired and nobody was paged. " * 5 + "</p>"
        "</article></body></html>"
    )
    types = [c.section_type for c in chunk.chunk_html(html)]
    assert types == ["summary", "root_cause"]


def test_br_separated_text_uses_line_fallback():
    body = "<br>".join(f"Line {i} of the incident report with some detail." for i in range(40))
    chunks = chunk.chunk_html(f"<html><body><div>{body}</div></body></html>", max_chars=400)
    assert len(chunks) >= 3
    assert "Line 39 " in " ".join(c.text for c in chunks)


def test_empty_or_tiny_documents_yield_no_chunks():
    assert chunk.chunk_html("<html><body></body></html>") == []
    assert chunk.chunk_html("<html><body><h1>Title</h1><p>Hi</p></body></html>") == []


def test_heading_classification():
    assert chunk.classify_heading("What happened") == "summary"
    assert chunk.classify_heading("Why did this happen?") == "root_cause"
    assert chunk.classify_heading("Action items") == "remediation"
    assert chunk.classify_heading("Customer impact") == "impact"
    assert chunk.classify_heading("Credits") == "other"


def test_largest_container_wins_over_small_article_cards():
    body = "<p>" + "The failover script promoted a stale replica to primary. " * 20 + "</p>"
    html = (
        "<html><body><main><article><p>Related card</p></article>"
        f"<h2>Root cause</h2>{body}</main></body></html>"
    )
    chunks = chunk.chunk_html(html)
    root = [c for c in chunks if c.section_type == "root_cause"]
    assert root and all("stale replica" in c.text for c in root)
    assert not any("Related card" in c.text for c in root)


def test_short_sections_are_kept_with_their_heading():
    html = (
        "<html><body><article><p>" + "Intro about the outage and what broke. " * 4 + "</p>"
        "<h2>Impact</h2><p>Users saw 5xx for 12 minutes.</p>"
        "<h2>Fix</h2><p>Rolled back the change.</p></article></body></html>"
    )
    by_type = {c.section_type: c.text for c in chunk.chunk_html(html)}
    assert by_type["impact"] == "Impact\nUsers saw 5xx for 12 minutes."
    assert by_type["remediation"] == "Fix\nRolled back the change."


def test_text_outside_block_tags_is_not_dropped_even_next_to_paragraphs():
    html = (
        "<html><body><article>"
        "<p>" + "A long paragraph describing the first part of the incident. " * 12 + "</p>"
        "<div>Loose text in a div that says the cache layer was saturated by retries.</div>"
        "<div>Direct text before a child. <span>inline part stays joined.</span>"
        "<p>Child paragraph follows.</p>Trailing loose text after the child.</div>"
        "</article></body></html>"
    )
    text = " ".join(c.text for c in chunk.chunk_html(html))
    assert "cache layer was saturated by retries" in text
    assert "Direct text before a child. inline part stays joined." in text
    assert "Child paragraph follows." in text
    assert "Trailing loose text after the child." in text


def test_heading_is_budgeted_into_the_chunk_size_cap():
    heading = "Root cause analysis of the primary failure"
    body = " ".join(f"Sentence {i} explains the failure in some detail." for i in range(60))
    chunks = chunk.chunk_html(
        f"<html><body><article><h2>{heading}</h2><p>{body}</p></article></body></html>",
        max_chars=300,
    )
    assert len(chunks) > 3
    assert all(len(c.text) <= 300 and c.text.startswith(heading) for c in chunks)
