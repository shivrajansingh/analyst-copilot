from analyst_copilot.parsing.html_filing_parser import parse_filing_html


def test_3m_parsing_finds_cash_flow_page():
    from analyst_copilot.config.settings import get_settings

    settings = get_settings()
    document = parse_filing_html(settings.filings_dir / "3M_2018_10K.htm")

    assert document.page_count > 50
    capex_pages = [
        p
        for p in document.pages
        if "Purchases of property, plant and equipment" in p.text and "1,577" in p.text
    ]
    assert capex_pages, "Expected cash-flow capex line item in parsed pages"
    assert any(p.printed_page == 60 for p in capex_pages)


def test_hr_page_breaks_are_recognized():
    """
    Most filings mark pages with <hr style="page-break-after:always">, not <p>.
    Missing this sends the filing down the character-chunking fallback, which
    makes every page citation meaningless.
    """
    from analyst_copilot.parsing.html_filing_parser import (
        FALLBACK_CHARS_PER_PAGE,
        PAGE_BREAK_PATTERN,
    )

    for markup in (
        '<hr style="page-break-after:always">',
        '<hr style="page-break-after:always"/>',
        '<p style="page-break-after: always">',
        '<div style="page-break-after:always">',
        '<hr style="break-after:always">',
    ):
        assert PAGE_BREAK_PATTERN.search(markup), f"not matched: {markup}"

    html = "<html><body>"
    html += '<p>Alpha page</p><hr style="page-break-after:always"/>'
    html += '<p>Beta page</p><hr style="page-break-after:always"/>'
    html += "<p>Gamma page</p></body></html>"

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "TEST_10K.htm"
        path.write_text(html, encoding="utf-8")
        document = parse_filing_html(path)

    assert document.page_count == 3, document.page_count
    assert [p.page_index for p in document.pages] == [0, 1, 2]
    # citation_page must be the 0-based index, not a printed footer number
    assert [p.citation_page for p in document.pages] == [0, 1, 2]
    assert [p.display_page for p in document.pages] == [1, 2, 3]
    # nothing should be long enough to look like a fallback slice
    assert all(len(p.text) < FALLBACK_CHARS_PER_PAGE for p in document.pages)


def test_corpus_mostly_avoids_the_chunking_fallback():
    """Guard the regression that sent 78 of 79 filings to the fallback path."""
    from analyst_copilot.config.settings import get_settings
    from analyst_copilot.parsing.html_filing_parser import (
        PAGE_BREAK_PATTERN,
        _extract_html_body,
    )

    settings = get_settings()
    paths = sorted(settings.filings_dir.glob("*.htm"))
    if len(paths) < 10:
        import pytest

        pytest.skip("filings corpus not present")

    with_breaks = sum(
        1
        for path in paths
        if PAGE_BREAK_PATTERN.search(
            _extract_html_body(path.read_text(encoding="utf-8", errors="ignore"))
        )
    )
    assert with_breaks / len(paths) > 0.9, f"only {with_breaks}/{len(paths)} have page breaks"
