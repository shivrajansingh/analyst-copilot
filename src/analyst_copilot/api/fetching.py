"""Fetch a document from a URL the user supplied.

**This is the one place the service makes an outbound request to an address a
user chose**, which makes it the one place server-side request forgery is
possible. A naive implementation here lets anyone with access to the chat box
read the cloud metadata endpoint, probe the internal network, or pull a file
off `localhost` — using the server's own credentials and network position.

The guards, in the order they run:

1. **Scheme allowlist.** `http`/`https` only. `file://`, `gopher://` and
   friends are refused outright.
2. **Address check.** The hostname is resolved and *every* address it returns is
   checked. Loopback, private, link-local (which covers the 169.254.169.254
   metadata endpoint), reserved and multicast ranges are refused. One public and
   one private address on the same name is still a refusal.
3. **Manual redirects.** Redirects are followed by hand, capped, and the address
   check runs again on every hop — otherwise a public URL that 302s to
   `http://169.254.169.254/` walks straight past step 2.
4. **Size cap, enforced while streaming.** `Content-Length` is a claim, not a
   fact, so the limit is applied to bytes as they arrive and the download is
   abandoned the moment it is exceeded.
5. **Timeout** on every hop.

**Residual risk, stated plainly:** a name that resolves to a public address
during the check and a private one at connect time (DNS rebinding) would defeat
step 2, because the check and the connection are separate resolutions. Closing
that properly means pinning the connection to the validated IP and carrying the
hostname in the `Host` header, which urllib does not make easy. For an
internal-facing analyst tool this is an accepted gap; it should be closed before
the service is exposed to untrusted users.

Fetching from private addresses can be enabled deliberately —
`API_ALLOW_PRIVATE_NETWORK_FETCH=true` — for a deployment whose document store
is on the same internal network.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
# Some archives refuse anonymous clients. SEC's fair-access policy in particular
# wants a contact address in the User-Agent and answers 403 without one, so this
# is configurable via `API_FETCH_USER_AGENT`.
DEFAULT_USER_AGENT = "analyst-copilot/1.0 (+https://github.com/analyst-copilot)"
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT_SECONDS = 30
_CHUNK = 256 * 1024

# Formats a server may claim that map cleanly onto a parser. Used only when the
# URL and Content-Disposition give no usable filename.
_CONTENT_TYPE_SUFFIX = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

_FILENAME_STAR = re.compile(r"filename\*\s*=\s*[^']*''([^;]+)", re.IGNORECASE)
_FILENAME = re.compile(r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)', re.IGNORECASE)


class FetchError(Exception):
    """The URL could not be fetched, with a reason worth showing the user."""


@dataclass
class FetchedFile:
    """What came back: where it was written, and what it appears to be."""

    path: Path
    filename: str
    suffix: str
    bytes_written: int
    final_url: str
    content_type: Optional[str]


class RemoteDocumentFetcher:
    """Download a user-supplied URL to disk, safely and with a size ceiling."""

    def __init__(
        self,
        max_bytes: int,
        allowed_suffixes: Tuple[str, ...],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        allow_private_network: bool = False,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._max_bytes = max_bytes
        self._allowed = tuple(s.lower() for s in allowed_suffixes)
        self._timeout = timeout_seconds
        self._allow_private = allow_private_network
        self._user_agent = user_agent

    def fetch(self, url: str, destination_dir: Path, doc_name: Optional[str] = None) -> FetchedFile:
        """
        Download `url` into `destination_dir` and return what landed.

        The file is written under a `.part` name and moved into place only once
        it has arrived complete, so an interrupted download never leaves a
        truncated document looking like a finished one.
        """
        response, final_url = self._open(url)
        try:
            filename, suffix = self._name_for(final_url, response, doc_name)
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / filename
            partial = destination.with_name(f"{destination.name}.part")

            written = 0
            try:
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self._max_bytes:
                            raise FetchError(
                                f"The file at {url} is larger than the "
                                f"{self._max_bytes // (1024 * 1024)} MB limit."
                            )
                        handle.write(chunk)
                if written == 0:
                    raise FetchError(f"{url} returned an empty file.")
                partial.replace(destination)
            except BaseException:
                partial.unlink(missing_ok=True)
                raise

            return FetchedFile(
                path=destination,
                filename=filename,
                suffix=suffix,
                bytes_written=written,
                final_url=final_url,
                content_type=response.headers.get("Content-Type"),
            )
        finally:
            response.close()

    # -- transport ---------------------------------------------------------- #
    def _open(self, url: str):
        """Follow redirects by hand, validating every hop."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self._validate(current)
            request = Request(
                current,
                headers={"User-Agent": self._user_agent, "Accept": "*/*"},
                method="GET",
            )
            try:
                response = _NoRedirect().open(request, timeout=self._timeout)
            except HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    location = exc.headers.get("Location")
                    exc.close()
                    if not location:
                        raise FetchError(f"{current} redirected without a destination.")
                    current = _resolve_redirect(current, location)
                    continue
                raise FetchError(
                    f"{current} returned HTTP {exc.code} ({exc.reason})."
                ) from exc
            except URLError as exc:
                raise FetchError(f"Could not reach {current}: {exc.reason}") from exc
            except (socket.timeout, TimeoutError) as exc:
                raise FetchError(f"{current} did not respond within {self._timeout}s.") from exc

            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > self._max_bytes:
                response.close()
                raise FetchError(
                    f"The file at {current} declares "
                    f"{int(declared) // (1024 * 1024)} MB, over the "
                    f"{self._max_bytes // (1024 * 1024)} MB limit."
                )
            return response, current

        raise FetchError(f"{url} redirected more than {MAX_REDIRECTS} times.")

    def _validate(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            raise FetchError(
                f"Only http and https URLs are supported; got {parsed.scheme or '(none)'}."
            )
        host = parsed.hostname
        if not host:
            raise FetchError(f"{url} has no host.")
        if self._allow_private:
            return

        for address in _resolve(host):
            if not _is_public(address):
                raise FetchError(
                    f"{host} resolves to {address}, which is not a public address. "
                    "Fetching from private, loopback or link-local addresses is "
                    "disabled."
                )

    # -- naming -------------------------------------------------------------- #
    def _name_for(self, url: str, response, doc_name: Optional[str]) -> Tuple[str, str]:
        """
        Work out what to call the file, and refuse formats we cannot parse.

        The URL path is tried first, then `Content-Disposition`, then the
        content type. A URL ending in `/download` says nothing about format, so
        the header is what saves that case.
        """
        candidates = [
            _filename_from_disposition(response.headers.get("Content-Disposition")),
            Path(unquote(urlparse(url).path)).name,
        ]
        suffix = ""
        for candidate in candidates:
            if candidate and Path(candidate).suffix.lower() in self._allowed:
                suffix = Path(candidate).suffix.lower()
                break

        if not suffix:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            mapped = _CONTENT_TYPE_SUFFIX.get(content_type)
            if mapped and mapped in self._allowed:
                suffix = mapped

        if not suffix:
            raise FetchError(
                f"Could not tell what kind of document {url} is. "
                f"Supported types: {', '.join(self._allowed)}."
            )

        stem = doc_name or next(
            (Path(c).stem for c in candidates if c and Path(c).stem),
            "",
        ) or "document"
        return f"{stem}{suffix}", suffix


class _NoRedirect:
    """An opener that surfaces redirects as errors so they can be re-validated."""

    def __init__(self) -> None:
        from urllib.request import HTTPRedirectHandler, build_opener

        class _Blocked(HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):  # noqa: D102
                return None

        self._opener = build_opener(_Blocked)

    def open(self, request, timeout):
        return self._opener.open(request, timeout=timeout)


def _resolve_redirect(base: str, location: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, location)


def _resolve(host: str) -> Set[str]:
    """Every address the hostname resolves to. A literal IP resolves to itself."""
    try:
        ipaddress.ip_address(host)
        return {host}
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}: {exc.strerror or exc}") from exc
    return {info[4][0] for info in infos}


# IPv6 prefixes that carry an IPv4 address in their low 32 bits. On a NAT64 /
# DNS64 network -- which some ISPs and most corporate VPNs now run -- a resolver
# returns `64:ff9b::<v4>` for an IPv4-only host, and Python reports that whole
# range as reserved. Judging it without unwrapping refuses every ordinary public
# URL on such a network.
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")


def _unwrap_v4(parsed: ipaddress.IPv6Address) -> Optional[ipaddress.IPv4Address]:
    """The IPv4 address embedded in a v6 address, when there is one."""
    if parsed.ipv4_mapped is not None:      # ::ffff:a.b.c.d
        return parsed.ipv4_mapped
    if parsed.sixtofour is not None:        # 2002:<v4>::/48
        return parsed.sixtofour
    if parsed in _NAT64_WELL_KNOWN:         # 64:ff9b::<v4>
        return ipaddress.IPv4Address(int(parsed) & 0xFFFFFFFF)
    return None


def _is_public(address: str) -> bool:
    """
    Whether an address is one we are willing to make a request to.

    A v4 address wrapped in v6 is judged on the address it actually reaches, so
    NAT64 does not break ordinary fetches. This cannot be used to smuggle a
    private target past the guard: the unwrapped address goes through exactly
    the same predicates, so `::ffff:127.0.0.1` and `64:ff9b::7f00:1` are both
    still refused as loopback.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False

    if isinstance(parsed, ipaddress.IPv6Address):
        embedded = _unwrap_v4(parsed)
        if embedded is not None:
            return _is_public(str(embedded))

    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def _filename_from_disposition(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    starred = _FILENAME_STAR.search(header)
    if starred:
        return Path(unquote(starred.group(1)).strip().strip('"')).name
    match = _FILENAME.search(header)
    if not match:
        return None
    value = (match.group(1) or match.group(2) or "").strip().strip('"')
    return Path(value).name or None
