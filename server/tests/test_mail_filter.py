"""The newsletter and promotion filter of the deadline scan (synthetic mail only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from agent.proactive.mailfilter import is_bulk_mail, is_trusted_sender
from tests.proactive_support import ProEnv, mail_message, make_env

NEWSLETTERS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "fixtures" / "newsletters.json").read_text(encoding="utf-8")
)
COLLEGE_DOMAIN = "example.edu"
VIP = "boss@example.net"
MARKET = NEWSLETTERS[0]


def _fields(item: dict[str, Any], **changes: Any) -> dict[str, Any]:
    fields = {
        "from_addr": item["from_addr"],
        "from_name": item["from_name"],
        "subject": item["subject"],
        "body": item["body"],
        "label_ids": tuple(item["label_ids"]),
        "list_unsubscribe": item["list_unsubscribe"],
    }
    fields.update(changes)
    return fields


def _env() -> ProEnv:
    return make_env(college_domains=(COLLEGE_DOMAIN.upper(),), vip_senders=(VIP.upper(),))


# --- the pure functions ------------------------------------------------------------------------


@pytest.mark.parametrize("item", NEWSLETTERS, ids=lambda i: i["name"])
def test_every_fixture_is_flagged_with_its_reason(item: dict[str, Any]) -> None:
    reason = is_bulk_mail(
        item["from_addr"],
        item["subject"],
        item["body"],
        item["label_ids"],
        item["list_unsubscribe"],
    )
    assert reason == item["expect_reason"]


def test_ordinary_mail_is_not_bulk() -> None:
    assert (
        is_bulk_mail(
            "registrar@example.org",
            "Fee reminder",
            "The tuition fee is due on 12 Oct 2026.",
            ["INBOX", "UNREAD", "CATEGORY_UPDATES"],
            False,
        )
        is None
    )
    # "news" or "offers" inside a longer local part or the domain is not a bulk sender
    for addr in ("newsroom@example.org", "john.deals@example.org", "me@news.example.org"):
        assert is_bulk_mail(addr, "Hello", "Hello", [], False) is None
    assert is_bulk_mail("", "Hello", "Hello", [], False) is None


@pytest.mark.parametrize(
    "text",
    [
        "Click to UNSUBSCRIBE",
        "Read our Newsletter",
        "View this email in your browser",
        "view it in browser",
        "Manage your email preferences",
        "manage subscriptions",
        "Your Monthly Roundup",
        "daily briefing",
        "You're receiving this email",
        "you are receiving this because",
        "Market Wrap: stocks rally",
        "market outlook for October",
    ],
)
def test_newsletter_text_signals(text: str) -> None:
    assert is_bulk_mail("a@example.org", text, "", [], False) == "newsletter_text"
    assert is_bulk_mail("a@example.org", "Hi", f"intro. {text}.", [], False) == "newsletter_text"


@pytest.mark.parametrize("label", ["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS"])
def test_bulk_labels(label: str) -> None:
    assert is_bulk_mail("a@example.org", "Hi", "Hi", ["INBOX", label], False) == "bulk_label"
    assert is_bulk_mail("a@example.org", "Hi", "Hi", ["CATEGORY_UPDATES"], False) is None


@pytest.mark.parametrize(
    "local",
    [
        *("newsletter", "newsletters", "news", "digest", "marketing"),
        *("promo", "promos", "promotions", "offers", "deals", "mailer"),
        *("campaign", "campaigns", "NewsLetter"),
    ],
)
def test_bulk_sender_local_parts(local: str) -> None:
    assert is_bulk_mail(f"{local}@example.org", "Hi", "Hi", [], False) == "bulk_sender"


def test_trusted_senders_match_the_way_the_classifier_does() -> None:
    vip, college = frozenset({VIP}), frozenset({COLLEGE_DOMAIN})
    assert is_trusted_sender(VIP, vip, college)
    assert is_trusted_sender(VIP.upper(), vip, college)
    assert not is_trusted_sender("x" + VIP, vip, college)  # exact address only
    assert is_trusted_sender(f"a@{COLLEGE_DOMAIN}", vip, college)
    assert is_trusted_sender(f"a@mail.{COLLEGE_DOMAIN}", vip, college)
    assert not is_trusted_sender(f"a@not{COLLEGE_DOMAIN}", vip, college)
    assert not is_trusted_sender(f"a@{COLLEGE_DOMAIN}.example.com", vip, college)
    assert not is_trusted_sender("", vip, college)
    assert not is_trusted_sender("a@example.com", frozenset(), frozenset())


# --- in the deadline scan ----------------------------------------------------------------------


@pytest.mark.parametrize("item", NEWSLETTERS, ids=lambda i: i["name"])
def test_a_newsletter_yields_no_deadline(item: dict[str, Any]) -> None:
    env = _env()
    env.deliver(mail_message("n1", **_fields(item)))
    assert env.deadlines() == []
    assert env.db.query("SELECT * FROM deadlines") == []
    assert env.services.autocal.run() == 0 and env.calendar.inserted == []
    # the mail counts as looked at, so the catch-up never revisits it
    assert [r["message_id"] for r in env.db.query("SELECT * FROM mail_deadline_scans")] == ["n1"]


@pytest.mark.parametrize("item", NEWSLETTERS, ids=lambda i: i["name"])
def test_the_same_text_from_a_college_domain_yields_a_deadline(item: dict[str, Any]) -> None:
    env = _env()
    sender = f"office@mail.{COLLEGE_DOMAIN}"
    env.deliver(mail_message("c1", **_fields(item, from_addr=sender)))
    assert len(env.deadlines()) >= 1


@pytest.mark.parametrize("item", NEWSLETTERS, ids=lambda i: i["name"])
def test_the_same_text_from_a_vip_yields_a_deadline(item: dict[str, Any]) -> None:
    env = _env()
    env.deliver(mail_message("v1", **_fields(item, from_addr=VIP)))
    assert len(env.deadlines()) >= 1


def test_the_market_newsletter_would_have_been_a_deadline_without_the_filter() -> None:
    env = _env()
    env.deliver(mail_message("c1", **_fields(MARKET, from_addr=f"x@{COLLEGE_DOMAIN}")))
    due_days = sorted(d.due.isoformat()[:10] for d in env.deadlines())
    assert "2026-10-08" in due_days  # "The Fed meeting is on 8 October"


def test_the_catch_up_scan_applies_the_filter_too() -> None:
    env = _env()
    env.store_mail(mail_message("n1", **_fields(MARKET)))
    env.store_mail(mail_message("c1", **_fields(MARKET, from_addr=f"x@{COLLEGE_DOMAIN}")))
    result = env.services.deadlines.scan_stored_mail()
    assert (result.scanned, result.failed) == (2, 0)
    assert {d.source_id for d in env.deadlines()} == {"c1"}


def test_filtering_logs_only_a_reason_code(caplog: pytest.LogCaptureFixture) -> None:
    env = _env()
    with caplog.at_level(logging.INFO, logger="agent"):
        env.deliver(mail_message("n1", **_fields(MARKET)))
    assert "list_unsubscribe" in caplog.text
    for secret in (MARKET["from_addr"], "wire.example.com", MARKET["subject"], "Crude"):
        assert secret not in caplog.text


def test_normal_mail_is_still_scanned() -> None:
    env = _env()
    env.deliver(mail_message("m1"))
    [item] = env.deadlines()
    assert (item.kind, item.source_id) == ("fee", "m1")
