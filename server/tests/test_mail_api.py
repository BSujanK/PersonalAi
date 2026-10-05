from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
