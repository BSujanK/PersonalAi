from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.connectors.gmail import GmailApi, MailMessage
from agent.mail.services import MailServices
from agent.mail.store import MailStore
from agent.mail.sync import MailSync
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore
from tests.fakes_gmail import FakeGmailApi
from tests.support import START, FakeClock, make_registry
from tests.test_api import _auth
from tests.test_loop import FakeLLM, say

ACCOUNT = "me@example.com"
NOW_MS = int(START.timestamp() * 1000)


@dataclass
class MailApi:
    client: TestClient
    store: MailStore
    db: Database
    headers: dict[str, str]


def _mail_api() -> MailApi:
    db = Database(":memory:")
    clock = FakeClock()
    keystore = KeyStore()
    key = keystore.get_or_create_bytes("db_key")
    store = MailStore(db, FieldCipher(key), key, clock)
    api = FakeGmailApi(ACCOUNT)

    def api_for(_account: str) -> GmailApi:
        return api

    services = MailServices(store, MailSync(store, api_for, None, clock, 7), api_for)
    app = create_app(
        Settings(owner_emails=(ACCOUNT,)),
        db=db,
        keystore=keystore,
        llm=FakeLLM(say("hi")),
        registry=make_registry([]),
        clock=clock,
        mail=services,
    )
    client = TestClient(app)
    code = open_pairing_window(db, clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    return MailApi(client, store, db, _auth(paired))


def _store_mail(store: MailStore, message_id: str, **kw: Any) -> None:
    base: dict[str, Any] = {
        "account": ACCOUNT,
        "id": message_id,
        "thread_id": "t",
        "history_id": "1",
        "internal_date": NOW_MS - 1000,
        "from_addr": "alice@example.com",
        "from_name": "Alice",
        "to": (ACCOUNT,),
        "subject": f"Subject {message_id}",
        "snippet": "snip",
        "body": "body",
        "label_ids": ("INBOX",),
        "list_unsubscribe": False,
    }
    base.update(kw)
    store.upsert(MailMessage(**base))


def test_digest_endpoint() -> None:
    api = _mail_api()
    _store_mail(api.store, "m1")
    _store_mail(api.store, "m2", internal_date=NOW_MS - 48 * 3_600_000)
    api.store.set_category(ACCOUNT, "m1", "important", "rule", "vip")
    body = api.client.get("/mail/digest", headers=api.headers).json()
    assert [i["id"] for i in body["important"]] == ["m1"]
    assert body["counts"]["important"] == 1 and body["unclassified"] == 0
    wide = api.client.get("/mail/digest?hours=72", headers=api.headers).json()
    assert wide["unclassified"] == 1
    assert api.client.get("/mail/digest?hours=0", headers=api.headers).status_code == 422
    assert api.client.get("/mail/digest?hours=169", headers=api.headers).status_code == 422


def test_feedback_updates_message_rule_and_audit() -> None:
    api = _mail_api()
    _store_mail(api.store, "m1")
    _store_mail(api.store, "m2")
    api.store.set_category(ACCOUNT, "m1", "normal", "llm", "llm")
    resp = api.client.post(
        "/mail/feedback",
        headers=api.headers,
        json={"account": ACCOUNT, "message_id": "m1", "category": "promo"},
    )
    assert resp.status_code == 200
    stored = api.store.get(ACCOUNT, "m1")
    assert stored is not None
    assert (stored.category, stored.category_source) == ("promo", "feedback")
    assert api.store.sender_rule("alice@example.com") == "promo"
    feedback = api.store.recent_feedback(5)
    assert [(f.mail.id, f.new_category) for f in feedback] == [("m1", "promo")]
    row = api.db.query("SELECT old_category FROM mail_feedback")[0]
    assert row["old_category"] == "normal"
    audit = api.db.query("SELECT event, detail FROM audit_log WHERE event = 'mail_feedback'")
    assert [(r["event"], r["detail"]) for r in audit] == [("mail_feedback", "promo")]


def test_feedback_validation() -> None:
    api = _mail_api()
    missing = api.client.post(
        "/mail/feedback",
        headers=api.headers,
        json={"account": ACCOUNT, "message_id": "nope", "category": "spam"},
    )
    assert missing.status_code == 404
    bad = api.client.post(
        "/mail/feedback",
        headers=api.headers,
        json={"account": ACCOUNT, "message_id": "m1", "category": "urgent"},
    )
    assert bad.status_code == 422


def test_mail_routes_absent_without_mail_services() -> None:
    db = Database(":memory:")
    app = create_app(
        Settings(),
        db=db,
        keystore=KeyStore(),
        llm=FakeLLM(say("hi")),
        registry=make_registry([]),
        clock=FakeClock(),
    )
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not any(p.startswith("/mail") for p in paths)
    assert not hasattr(app.state, "mail")


# --- GET /mail/inbox ---------------------------------------------------------------------------

INBOX_ORDER = ("important", "normal", None, "promo", "spam")


def _seed_inbox(api: MailApi) -> None:
    """Two mails per category (and two unclassified), newest has the highest number."""
    for rank, category in enumerate(INBOX_ORDER):
        for n in range(2):
            message_id = f"{category or 'none'}-{n}"
            _store_mail(api.store, message_id, internal_date=NOW_MS - 1000 * (10 * rank + n))
            if category is not None:
                api.store.set_category(ACCOUNT, message_id, category, "rule", "test")


def _inbox(api: MailApi, query: str = "") -> dict[str, Any]:
    response = api.client.get(f"/mail/inbox?{query}", headers=api.headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["items"]]


def test_inbox_orders_by_category_rank_then_newest() -> None:
    api = _mail_api()
    _seed_inbox(api)
    body = _inbox(api)
    assert _ids(body) == [
        "important-0", "important-1", "normal-0", "normal-1", "none-0", "none-1",
        "promo-0", "promo-1", "spam-0", "spam-1",
    ]  # fmt: skip
    assert body["next_cursor"] is None
    assert body["counts"] == {
        "important": 2, "normal": 2, "promo": 2, "spam": 2, "unclassified": 2,
    }  # fmt: skip


def test_inbox_item_shape_and_unread_flag() -> None:
    api = _mail_api()
    _store_mail(api.store, "m1", label_ids=("INBOX", "UNREAD"), from_name="Alice")
    _store_mail(api.store, "m2", label_ids=("INBOX",), internal_date=NOW_MS - 5000)
    api.store.set_category(ACCOUNT, "m1", "important", "rule", "vip")
    first, second = _inbox(api)["items"]
    assert first == {
        "account": ACCOUNT,
        "id": "m1",
        "message_id": "m1",
        "thread_id": "t",
        "category": "important",
        "from_name": "Alice",
        "from_addr": "alice@example.com",
        "subject": "Subject m1",
        "snippet": "snip",
        "reason": "vip",
        "received": "2026-10-05T11:59:59+00:00",
        "unread": True,
    }
    assert (second["category"], second["reason"], second["unread"]) == (None, None, False)


def test_inbox_excludes_deleted_messages_everywhere() -> None:
    api = _mail_api()
    _seed_inbox(api)
    api.store.mark_deleted(ACCOUNT, "important-0")
    body = _inbox(api)
    assert "important-0" not in _ids(body) and body["counts"]["important"] == 1


def test_inbox_pages_through_every_message_once_in_order() -> None:
    api = _mail_api()
    _seed_inbox(api)
    full = _ids(_inbox(api))
    for size in (1, 3, 4):
        seen: list[str] = []
        cursor: str | None = None
        for _ in range(20):
            query = f"limit={size}" + (f"&cursor={cursor}" if cursor else "")
            page = _inbox(api, query)
            assert len(page["items"]) <= size
            seen += _ids(page)
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert seen == full, size


def test_inbox_cursor_breaks_ties_by_account_then_id() -> None:
    api = _mail_api()
    for account, message_id in (("b@example.com", "z"), (ACCOUNT, "y"), (ACCOUNT, "x")):
        _store_mail(api.store, message_id, account=account, internal_date=NOW_MS - 1)
    seen: list[tuple[str, str]] = []
    cursor: str | None = None
    while True:
        page = _inbox(api, "limit=1" + (f"&cursor={cursor}" if cursor else ""))
        seen += [(i["account"], i["id"]) for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [("b@example.com", "z"), (ACCOUNT, "x"), (ACCOUNT, "y")]


def test_inbox_category_filter_is_repeatable_and_counts_ignore_it() -> None:
    api = _mail_api()
    _seed_inbox(api)
    body = _inbox(api, "category=promo&category=unclassified")
    assert _ids(body) == ["none-0", "none-1", "promo-0", "promo-1"]
    assert body["counts"]["important"] == 2
    assert _ids(_inbox(api, "category=spam")) == ["spam-0", "spam-1"]
    paged = _inbox(api, "category=unclassified&limit=1")
    assert _ids(paged) == ["none-0"] and paged["next_cursor"] is not None
    assert _ids(_inbox(api, f"category=unclassified&limit=1&cursor={paged['next_cursor']}")) == [
        "none-1"
    ]


def test_inbox_validates_parameters() -> None:
    api = _mail_api()
    for query in (
        "limit=0",
        "limit=101",
        "limit=x",
        "category=urgent",
        "category=important&category=x",
    ):
        assert api.client.get(f"/mail/inbox?{query}", headers=api.headers).status_code == 422, query
    assert api.client.get("/mail/inbox?limit=100", headers=api.headers).status_code == 200


def _cursor(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "!!!",
        "bm90IGpzb24",  # base64 of "not json"
        _cursor({"rank": 0}),
        _cursor([0, 1, "a"]),
        _cursor([0, 1, "a", "b", "c"]),
        _cursor(["0", 1, "a", "b"]),
        _cursor([0, "1", "a", "b"]),
        _cursor([0, 1, 2, "b"]),
        _cursor([0, 1, "a", None]),
        _cursor([True, 1, "a", "b"]),
        _cursor([9, 1, "a", "b"]),
        _cursor([-1, 1, "a", "b"]),
    ],
)
def test_inbox_rejects_malformed_cursors(cursor: str) -> None:
    api = _mail_api()
    response = api.client.get(f"/mail/inbox?cursor={cursor}", headers=api.headers)
    assert (response.status_code, response.json()) == (400, {"detail": "bad_cursor"})


def test_inbox_needs_the_device_token() -> None:
    api = _mail_api()
    assert api.client.get("/mail/inbox").status_code in (401, 403)
