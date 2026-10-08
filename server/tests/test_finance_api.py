from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from agent.api.app import create_app
from agent.api.pair import open_pairing_window
from agent.config import Settings
from agent.core.redact import Redactor
from agent.finance.categorize import FinanceCategorizer
from agent.finance.services import FinanceServices
from agent.store.keystore import KeyStore
from tests.finance_support import SENDER, FinEnv, at, balance, make_fin, txn
from tests.support import START, make_registry
from tests.test_api import _auth
from tests.test_loop import FakeLLM, say

BODY = "Test body for the API"


@dataclass
class Api:
    client: TestClient
    env: FinEnv
    headers: dict[str, str]


def _api() -> Api:
    env = make_fin()
    env.parsers.sms[BODY] = txn()
    keystore = KeyStore()
    services = FinanceServices(
        env.store,
        env.ledger,
        env.ingest,
        FinanceCategorizer(env.store, None, Redactor()),
        env.reconciler,
    )
    app = create_app(
        Settings(finance_utc_offset_minutes=330),
        db=env.db,
        keystore=keystore,
        llm=FakeLLM(say("hi")),
        registry=make_registry([]),
        clock=env.clock,
        finance=services,
    )
    client = TestClient(app)
    code = open_pairing_window(env.db, env.clock, 300)
    paired = client.post("/pair", json={"code": code, "device_name": "Pixel"}).json()
    return Api(client, env, _auth(paired))


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _sms(api: Api, *items: dict[str, object]) -> object:
    return api.client.post("/sms", json={"messages": list(items)}, headers=api.headers)


def _item(body: str = BODY, offset_min: int = -5, sender: str = SENDER) -> dict[str, object]:
    return {
        "sender": sender,
        "body": body,
        "received_at": _ms(START + timedelta(minutes=offset_min)),
    }


def test_every_finance_route_needs_the_device_token() -> None:
    api = _api()
    for method, path in (
        ("post", "/sms"),
        ("get", "/sms/senders"),
        ("get", "/finance/summary"),
        ("get", "/finance/balances"),
        ("get", "/finance/transactions"),
        ("post", "/finance/category"),
    ):
        response = getattr(api.client, method)(path)
        assert response.status_code == 401, path
        bad = getattr(api.client, method)(path, headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401, path


def test_sms_batch_ingests_dedups_and_audits_counts_only() -> None:
    api = _api()
    response = _sms(api, _item(), _item("Promo", sender="AD-SHOP"))
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response.json() == {  # type: ignore[attr-defined]
        "accepted": 2,
        "duplicates": 0,
        "parsed": 1,
        "balances": 0,
        "ignored": 1,
        "unparsed": 0,
    }
    again = _sms(api, _item())
    assert again.json()["duplicates"] == 1  # type: ignore[attr-defined]
    rows = api.env.db.query("SELECT detail FROM audit_log WHERE event = 'sms_batch'")
    assert len(rows) == 2 and rows[0]["detail"].startswith("accepted=2 duplicates=0")
    assert BODY not in " ".join(r["detail"] for r in rows)


def test_invalid_batch_is_422_and_stores_nothing() -> None:
    api = _api()
    good = _item()
    for bad in (
        {**_item("x"), "sender": ""},
        {**_item("x"), "sender": "S" * 21},
        {**_item("x"), "body": "b" * 2001},
        {**_item("x"), "received_at": _ms(START + timedelta(days=1, minutes=1))},
        {**_item("x"), "received_at": -1},
        {**_item("x"), "received_at": 10**18},
        {**_item("x"), "received_at": "yesterday"},
    ):
        assert _sms(api, good, bad).status_code == 422  # type: ignore[attr-defined]
    assert api.client.post("/sms", json={"messages": []}, headers=api.headers).status_code == 422
    too_many = {"messages": [_item(f"b{i}") for i in range(501)]}
    assert api.client.post("/sms", json=too_many, headers=api.headers).status_code == 422
    assert api.env.db.query("SELECT 1 FROM finance_sms") == []
    assert api.env.db.query("SELECT 1 FROM audit_log WHERE event = 'sms_batch'") == []


def test_sms_senders_lists_the_phone_filter() -> None:
    api = _api()
    senders = api.client.get("/sms/senders", headers=api.headers).json()["senders"]
    assert {"BOBTXN", "BOBSMS", "HDFCBK"} <= set(senders)
    assert senders == sorted(senders)


def test_summary_balances_and_transactions_endpoints() -> None:
    api = _api()
    _sms(api, _item())
    api.env.ledger.record_balance(balance(balance_paise=100050), START, "sms")
    summary = api.client.get("/finance/summary?period=today", headers=api.headers).json()
    assert summary["spent_inr"] == "1234.50" and summary["count"] == 1
    balances = api.client.get("/finance/balances", headers=api.headers).json()
    assert balances["accounts"][0]["balance_inr"] == "1000.50"
    rows = api.client.get("/finance/transactions?period=today", headers=api.headers).json()
    assert rows["total"] == 1
    [row] = rows["transactions"]
    assert row["amount_inr"] == "1234.50" and row["counterparty"] == "Test Merchant"
    assert (row["account"], row["sources"], row["direction"]) == ("XX1234", ["sms"], "debit")
    assert api.client.get("/finance/summary?period=decade", headers=api.headers).status_code == 422
    assert api.client.get("/finance/transactions?limit=201", headers=api.headers).status_code == 422


def test_category_correction_remembers_counterparty_and_audits() -> None:
    api = _api()
    _sms(api, _item())
    [stored] = api.env.store.txns_between(START - timedelta(days=1), START + timedelta(days=1))
    response = api.client.post(
        "/finance/category",
        json={"txn_id": stored.id, "category": "shopping", "remember": True},
        headers=api.headers,
    )
    assert response.status_code == 200
    fixed = api.env.store.get_txn(stored.id)
    assert fixed is not None and (fixed.category, fixed.category_source) == ("shopping", "user")
    assert api.env.store.category_rule("Test Merchant") == "shopping"
    audit = api.env.db.query("SELECT detail, actor FROM audit_log WHERE event = 'finance_category'")
    assert audit[0]["detail"] == "shopping remember=True" and audit[0]["actor"].startswith(
        "device:"
    )
    assert "Test Merchant" not in audit[0]["detail"]


def test_category_correction_without_remember_and_errors() -> None:
    api = _api()
    _sms(api, _item())
    txn_id = api.env.db.query("SELECT id FROM finance_txns")[0]["id"]
    ok = api.client.post(
        "/finance/category", json={"txn_id": txn_id, "category": "rent"}, headers=api.headers
    )
    assert ok.status_code == 200 and api.env.store.category_rule("Test Merchant") is None
    missing = api.client.post(
        "/finance/category", json={"txn_id": 999, "category": "rent"}, headers=api.headers
    )
    assert missing.status_code == 404
    invalid = api.client.post(
        "/finance/category", json={"txn_id": txn_id, "category": "gold"}, headers=api.headers
    )
    assert invalid.status_code == 422


def test_sms_batch_records_the_last_ingest_time() -> None:
    from agent.store.sync_status import SMS_INGEST, last_ok

    api = _api()
    assert last_ok(api.env.db, SMS_INGEST) is None
    _sms(api, _item())
    assert last_ok(api.env.db, SMS_INGEST) == api.env.clock()


def test_sms_batch_nobody_could_parse_is_a_failure_not_ok() -> None:
    from agent.store.sync_status import SMS_INGEST, last_failure, last_ok

    api = _api()
    response = _sms(api, _item("Unreadable bank text one"), _item("Unreadable text two", -6))
    assert response.json()["unparsed"] == 2  # type: ignore[attr-defined]
    assert last_ok(api.env.db, SMS_INGEST) is None
    failure = last_failure(api.env.db, SMS_INGEST)
    assert failure is not None and failure.reason == "2 bank SMS could not be parsed"
    assert "Unreadable" not in failure.reason


def test_sms_batch_with_some_parsed_is_ok_and_clears_an_old_failure() -> None:
    from agent.store.sync_status import SMS_INGEST, last_failure, last_ok

    api = _api()
    _sms(api, _item("Unreadable bank text one"))
    assert last_failure(api.env.db, SMS_INGEST) is not None
    _sms(api, _item(), _item("Unreadable bank text one", -7))
    assert last_ok(api.env.db, SMS_INGEST) == api.env.clock()
    assert last_failure(api.env.db, SMS_INGEST) is None


def _gap_ledger(api: Api) -> None:
    """Two BoB readings 90 minutes apart whose balances leave 150.00 unexplained."""
    env = api.env
    env.ledger.record(txn(reference=None, balance_paise=90000, amount_paise=10000), at(-120), "sms")
    env.ledger.record(txn(reference=None, balance_paise=70000, amount_paise=5000), at(-30), "sms")
    env.reconciler.run()


def test_transactions_expose_inferred_rows_windows_and_the_notification_source() -> None:
    api = _api()
    _gap_ledger(api)
    api.env.ledger.record(
        txn(bank="upi", account_mask=None, reference=None, amount_paise=777),
        at(-5),
        "notification",
    )
    rows = api.client.get("/finance/transactions?period=today", headers=api.headers).json()
    by_amount = {r["amount_inr"]: r for r in rows["transactions"]}
    inferred = by_amount["150.00"]
    assert inferred["inferred"] is True and inferred["sources"] == []
    assert inferred["category"] == "unrecorded" and inferred["counterparty"] is None
    assert inferred["window"] == {"from": "2026-10-05T15:30+05:30", "to": "2026-10-05T17:00+05:30"}
    sms = by_amount["100.00"]
    assert sms["inferred"] is False and sms["window"] is None and sms["sources"] == ["sms"]
    assert by_amount["7.77"]["sources"] == ["notification"]


def test_summary_counts_unrecorded_money_and_balances_report_mismatches() -> None:
    api = _api()
    _gap_ledger(api)
    summary = api.client.get("/finance/summary?period=today", headers=api.headers).json()
    assert summary["spent_inr"] == "300.00" and summary["unrecorded_inr"] == "150.00"
    assert {"category": "unrecorded", "total_inr": "150.00", "count": 1} in summary["by_category"]
    assert api.client.get("/finance/balances", headers=api.headers).json()["mismatches"] == []

    api.env.ledger.record(
        txn(reference=None, balance_paise=-900000, amount_paise=100), at(-10), "sms"
    )
    api.env.reconciler.run()
    [mismatch] = api.client.get("/finance/balances", headers=api.headers).json()["mismatches"]
    assert mismatch == {
        "account": "XX1234",
        "from": "2026-10-05T17:00+05:30",
        "to": "2026-10-05T17:20+05:30",
        "amount_inr": "9699.00",
        "direction": "debit",
    }


def test_unrecorded_is_a_valid_category_for_the_owner_to_set() -> None:
    api = _api()
    _gap_ledger(api)
    [row] = [t for t in api.env.store.txns_between(at(-300), at(0)) if t.inferred]
    ok = api.client.post(
        "/finance/category", json={"txn_id": row.id, "category": "food"}, headers=api.headers
    )
    assert ok.status_code == 200
    again = api.client.post(
        "/finance/category", json={"txn_id": row.id, "category": "unrecorded"}, headers=api.headers
    )
    assert again.status_code == 200
