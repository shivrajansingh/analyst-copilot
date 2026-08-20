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
