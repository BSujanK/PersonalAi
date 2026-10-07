from __future__ import annotations

import ipaddress

from agent.main import wait_for_bind_addresses

LOCAL = ipaddress.ip_address("127.0.0.1")
TAILNET = ipaddress.ip_address("100.64.0.1")


def test_returns_at_once_when_every_address_exists() -> None:
    slept: list[float] = []
    missing = wait_for_bind_addresses([LOCAL, TAILNET], bindable=lambda h: True, sleep=slept.append)
    assert missing == [] and slept == []


def test_waits_until_a_late_address_comes_up() -> None:
    now = [0.0]
    ups = iter([False, False, True])

    def bindable(host: object) -> bool:
        return True if host == LOCAL else next(ups)

    def sleep(seconds: float) -> None:
        now[0] += seconds

    missing = wait_for_bind_addresses(
        [LOCAL, TAILNET], bindable=bindable, sleep=sleep, clock=lambda: now[0], poll=5.0
    )
    assert missing == [] and now[0] == 10.0


def test_gives_up_after_the_timeout_and_names_what_is_missing() -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    missing = wait_for_bind_addresses(
        [LOCAL, TAILNET],
        bindable=lambda h: h == LOCAL,
        sleep=sleep,
        clock=lambda: now[0],
        timeout=30.0,
        poll=5.0,
    )
    assert missing == [TAILNET] and now[0] >= 30.0


def test_loopback_is_really_bindable() -> None:
    assert wait_for_bind_addresses([LOCAL], timeout=0.0) == []
