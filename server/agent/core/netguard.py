"""Bind-address allowlist: loopback and Tailscale only (CLAUDE.md rule 5)."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from ipaddress import IPv4Address, IPv6Address

ALLOWED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)


class UnsafeBindAddress(ValueError):
    """Raised when a configured bind address is outside the allowlist."""


def validate_bind_address(host: str) -> IPv4Address | IPv6Address:
    text = host.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if "%" in text:
        raise UnsafeBindAddress("scoped/zone addresses are not allowed")
    try:
        addr: IPv4Address | IPv6Address = ipaddress.ip_address(text)
    except ValueError:
        raise UnsafeBindAddress("bind host must be an IP literal") from None
    if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_unspecified:
        raise UnsafeBindAddress("refusing to bind to an unspecified address")
    if not any(addr in net for net in ALLOWED_NETWORKS):
        raise UnsafeBindAddress("bind address is not loopback or Tailscale")
    return addr


def validate_bind_hosts(hosts: Iterable[str]) -> list[IPv4Address | IPv6Address]:
    validated = [validate_bind_address(h) for h in hosts]
    if not validated:
        raise UnsafeBindAddress("no bind hosts configured")
    return validated
