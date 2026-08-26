"""Fetching a document from a user-supplied URL, and refusing to be a proxy.

The address guards get the most coverage here on purpose. This is the only
endpoint that makes an outbound request to somewhere a user chose, so a gap in
it turns the service into an SSRF gadget with the server's own network position.
"""

import io
from pathlib import Path

import pytest

from analyst_copilot.api.fetching import (
    FetchError,
    RemoteDocumentFetcher,
    _filename_from_disposition,
    _is_public,
)

ALLOWED = (".pdf", ".htm", ".html", ".csv", ".docx", ".xlsx", ".md", ".txt")


def _fetcher(**overrides) -> RemoteDocumentFetcher:
    options = dict(max_bytes=1024 * 1024, allowed_suffixes=ALLOWED, timeout_seconds=5)
    options.update(overrides)
    return RemoteDocumentFetcher(**options)


class _Response:
    """The parts of an HTTP response the fetcher actually reads."""

    def __init__(self, body: bytes, headers: dict):
        self._stream = io.BytesIO(body)
        self.headers = headers

    def read(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


# -- address guards --------------------------------------------------------- #

@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",        # loopback
        "::1",              # loopback, v6
        "10.0.0.5",         # private
        "192.168.1.10",     # private
        "172.16.4.4",       # private
        "169.254.169.254",  # the cloud metadata endpoint
        "0.0.0.0",          # unspecified
        "224.0.0.1",        # multicast
        "fd00::1",          # unique local, v6
    ],
)
def test_non_public_addresses_are_not_public(address):
    assert _is_public(address) is False


@pytest.mark.parametrize("address", ["8.8.8.8", "93.184.216.34", "2606:2800:220:1::1"])
def test_public_addresses_are_public(address):
    assert _is_public(address) is True


def test_a_literal_private_address_is_refused():
    with pytest.raises(FetchError, match="not a public address"):
        _fetcher()._validate("http://169.254.169.254/latest/meta-data/")


def test_localhost_is_refused():
    with pytest.raises(FetchError, match="not a public address"):
        _fetcher()._validate("http://127.0.0.1:8000/api/v1/health")


def test_non_http_schemes_are_refused():
    for url in ("file:///etc/passwd", "gopher://example.com/", "ftp://example.com/a.pdf"):
        with pytest.raises(FetchError, match="Only http and https"):
            _fetcher()._validate(url)


def test_a_url_with_no_host_is_refused():
    with pytest.raises(FetchError, match="no host"):
        _fetcher()._validate("http:///nowhere.pdf")


def test_private_addresses_can_be_allowed_deliberately():
    """A deployment whose document store is internal can opt in."""
    _fetcher(allow_private_network=True)._validate("http://10.0.0.5/report.pdf")


def test_a_hostname_resolving_to_a_private_address_is_refused(monkeypatch):
    """A public-looking name that points inward must not slip through."""
    monkeypatch.setattr(
        "analyst_copilot.api.fetching._resolve", lambda host: {"10.1.2.3"}
    )
    with pytest.raises(FetchError, match="not a public address"):
        _fetcher()._validate("https://internal.example.com/report.pdf")


def test_one_private_address_among_several_is_still_a_refusal(monkeypatch):
    """Every address the name resolves to has to be public, not just one."""
    monkeypatch.setattr(
        "analyst_copilot.api.fetching._resolve", lambda host: {"93.184.216.34", "127.0.0.1"}
    )
    with pytest.raises(FetchError, match="not a public address"):
        _fetcher()._validate("https://split-horizon.example.com/report.pdf")


# -- naming ----------------------------------------------------------------- #

def test_filename_comes_from_the_url_path():
    fetcher = _fetcher()
    response = _Response(b"", {"Content-Type": "application/pdf"})
    name, suffix = fetcher._name_for("https://x.test/reports/AMD_2022_10K.pdf", response, None)
    assert (name, suffix) == ("AMD_2022_10K.pdf", ".pdf")


def test_content_disposition_beats_an_uninformative_path():
    """`/download` says nothing about format; the header is what saves it."""
    fetcher = _fetcher()
    response = _Response(
        b"",
        {
            "Content-Disposition": 'attachment; filename="BOEING_2022_10K.pdf"',
            "Content-Type": "application/octet-stream",
        },
    )
    name, suffix = fetcher._name_for("https://x.test/files/download", response, None)
    assert (name, suffix) == ("BOEING_2022_10K.pdf", ".pdf")


def test_content_type_is_the_last_resort():
    fetcher = _fetcher()
    response = _Response(b"", {"Content-Type": "text/csv; charset=utf-8"})
    name, suffix = fetcher._name_for("https://x.test/export", response, None)
    assert suffix == ".csv"


def test_an_unparseable_type_is_refused_rather_than_guessed():
    fetcher = _fetcher()
    response = _Response(b"", {"Content-Type": "image/png"})
    with pytest.raises(FetchError, match="Could not tell what kind"):
        fetcher._name_for("https://x.test/chart.png", response, None)


def test_an_explicit_doc_name_wins_but_keeps_the_real_suffix():
    fetcher = _fetcher()
    response = _Response(b"", {"Content-Type": "application/pdf"})
    name, suffix = fetcher._name_for("https://x.test/a/b.pdf", response, "3M_2018_10K")
    assert (name, suffix) == ("3M_2018_10K.pdf", ".pdf")


def test_a_traversing_filename_in_the_header_is_stripped_to_its_basename():
    assert _filename_from_disposition('attachment; filename="../../etc/passwd"') == "passwd"


def test_rfc5987_encoded_filenames_are_decoded():
    header = "attachment; filename*=UTF-8''3M%20report.pdf"
    assert _filename_from_disposition(header) == "3M report.pdf"


# -- download --------------------------------------------------------------- #

def test_a_fetched_file_lands_complete_with_no_part_left_behind(tmp_path, monkeypatch):
    body = b"%PDF-1.7\n" + b"x" * 500
    monkeypatch.setattr(
        RemoteDocumentFetcher,
        "_open",
        lambda self, url: (
            _Response(body, {"Content-Type": "application/pdf"}),
            "https://x.test/report.pdf",
        ),
    )

    result = _fetcher().fetch("https://x.test/report.pdf", tmp_path)

    assert result.path == tmp_path / "report.pdf"
    assert result.path.read_bytes() == body
    assert result.bytes_written == len(body)
    assert list(tmp_path.glob("*.part")) == []


def test_a_file_over_the_limit_is_abandoned_mid_stream(tmp_path, monkeypatch):
    """Content-Length is a claim; the cap has to hold against the bytes."""
    monkeypatch.setattr(
        RemoteDocumentFetcher,
        "_open",
        lambda self, url: (
            _Response(b"y" * 5000, {"Content-Type": "application/pdf"}),
            "https://x.test/big.pdf",
        ),
    )

    with pytest.raises(FetchError, match="larger than"):
        _fetcher(max_bytes=1000).fetch("https://x.test/big.pdf", tmp_path)

    # Nothing partial is left where a later run would mistake it for a document.
    assert list(tmp_path.iterdir()) == []


def test_an_empty_response_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(
        RemoteDocumentFetcher,
        "_open",
        lambda self, url: (
            _Response(b"", {"Content-Type": "application/pdf"}),
            "https://x.test/empty.pdf",
        ),
    )
    with pytest.raises(FetchError, match="empty file"):
        _fetcher().fetch("https://x.test/empty.pdf", tmp_path)
    assert list(tmp_path.iterdir()) == []
