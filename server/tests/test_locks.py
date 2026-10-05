from __future__ import annotations

import threading

from agent.core.locks import KeyedLocks


def test_same_key_serialises_and_registry_empties() -> None:
    locks = KeyedLocks()
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def first() -> None:
        with locks.hold("k"):
            order.append("first-in")
            inside.set()
            release.wait(5)
            order.append("first-out")

    def second() -> None:
        inside.wait(5)
        with locks.hold("k"):
            order.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    inside.wait(5)
    assert len(locks) >= 1
    release.set()
    for t in threads:
        t.join(5)
    assert order == ["first-in", "first-out", "second-in"]
    assert len(locks) == 0


def test_different_keys_do_not_block_each_other() -> None:
    locks = KeyedLocks()
    with locks.hold("a"):
        acquired = threading.Event()

        def other() -> None:
            with locks.hold("b"):
                acquired.set()

        t = threading.Thread(target=other)
        t.start()
        assert acquired.wait(5)
        t.join(5)
        assert len(locks) == 1
    assert len(locks) == 0


def test_lock_released_when_body_raises() -> None:
    locks = KeyedLocks()
    try:
        with locks.hold("a"):
            raise RuntimeError
    except RuntimeError:
        pass
    with locks.hold("a"):
        pass
    assert len(locks) == 0
