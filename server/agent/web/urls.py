"""Which URLs the web tools may fetch: public https hosts, port 443, no credentials."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

MAX_URL_CHARS = 2000
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")

Resolver = Callable[[str], list[str]]


def validate_web_url(url: str) -> str:
    """Return ``url`` unchanged if it is a fetchable web URL, else raise ``ValueError``.

    The messages are fixed text and never echo the URL.
    """
    if not url or len(url) > MAX_URL_CHARS:
        raise ValueError(f"a web URL must be 1 to {MAX_URL_CHARS} characters")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("a web URL must not contain whitespace or control characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("a web URL is malformed") from None
    if parts.scheme != "https" or not host:
        raise ValueError("a web URL must be https://")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("a web URL must not contain credentials")
    if port not in (None, 443):
        raise ValueError("a web URL must use port 443")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("a web URL must use a hostname, not an IP address")
    name = host.lower().rstrip(".")
    if (
        name == "localhost"
        or name.endswith(_BLOCKED_SUFFIXES)
        or "." not in name
        # An all-digit last label ("127.1", "0x7f.0.0.1") is an IP in disguise, not a domain.
        or name.rsplit(".", 1)[1].isdigit()
    ):
        raise ValueError("a web URL must use a public host name")
    return url


def default_resolver(host: str) -> list[str]:
    """Every address ``host`` resolves to; raises ``OSError`` when it does not resolve."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def check_resolves_public(host: str, resolver: Resolver = default_resolver) -> None:
    """Raise ``ValueError`` unless ``host`` resolves, and only to globally routable addresses."""
    try:
        addresses = resolver(host)
    except OSError:
        raise ValueError("the host could not be resolved") from None
    if not addresses:
        raise ValueError("the host could not be resolved")
    for raw in addresses:
        try:
            address = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            raise ValueError("the host resolved to an invalid address") from None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global or address.is_multicast:
            raise ValueError("the host resolves to a non-public address")
