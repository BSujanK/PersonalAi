from __future__ import annotations

import pytest

from agent.core.netguard import UnsafeBindAddress, validate_bind_address, validate_bind_hosts


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.5.5.5",
        "::1",
        "[::1]",
        "100.64.0.1",
        "100.127.255.254",
        "fd7a:115c:a1e0::1",
    ],
)
def test_accepts_loopback_and_tailscale(host: str) -> None:
    validate_bind_address(host)


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",  # noqa: S104
        "::",
        "192.168.1.10",
        "10.0.0.1",
        "172.16.0.1",
        "100.63.255.255",
        "100.128.0.0",
        "8.8.8.8",
        "::ffff:0.0.0.0",
        "::ffff:192.168.1.1",
        "fe80::1%eth0",
        "localhost",
        "",
        "127.0.0.1 extra",
        "fd7a:115c:a1e1::1",
    ],
)
def test_rejects_everything_else(host: str) -> None:
    with pytest.raises(UnsafeBindAddress):
        validate_bind_address(host)


def test_mapped_loopback_is_validated_as_ipv4() -> None:
    assert str(validate_bind_address("::ffff:127.0.0.1")) == "127.0.0.1"


def test_validate_bind_hosts() -> None:
    assert len(validate_bind_hosts(["127.0.0.1", "100.64.0.9"])) == 2
    with pytest.raises(UnsafeBindAddress):
        validate_bind_hosts([])
    with pytest.raises(UnsafeBindAddress):
        validate_bind_hosts(["127.0.0.1", "0.0.0.0"])  # noqa: S104
