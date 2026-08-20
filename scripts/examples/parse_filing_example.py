"""Parse a filing and print page statistics."""

from analyst_copilot.config.settings import get_settings
from analyst_copilot.parsing import parse_filing_html


def main() -> None:
    settings = get_settings()
    filing_path = settings.filings_dir / "3M_2018_10K.htm"
    document = parse_filing_html(filing_path)

    print(f"Document: {document.doc_name}")
    print(f"Source:   {document.source_path}")
    print(f"Pages:    {document.page_count}")

    # Show a few pages around the cash-flow statement (printed pages ~59–61)
    for page in document.pages:
        if page.printed_page in (59, 60, 61):
            preview = page.text[:200].replace("\n", " ")
            print(f"\n--- page_index={page.page_index}, printed_page={page.printed_page} ---")
            print(preview + "...")


if __name__ == "__main__":
    main()
