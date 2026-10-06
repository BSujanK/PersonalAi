from __future__ import annotations

import logging
from dataclasses import replace

import pytest

from agent.config import Settings, account_label
from tests.test_notifications_api import NotifyApi, _api, _get

# --- PERSONALAI_ACCOUNT_LABELS -----------------------------------------------------------------


def test_labels_parse_to_a_lower_cased_mapping() -> None:
    s = Settings.from_env(
        {"PERSONALAI_ACCOUNT_LABELS": " College@Example.edu = College , me@example.com=Home,"}
    )
    assert dict(s.account_labels) == {"college@example.edu": "College", "me@example.com": "Home"}
    assert dict(Settings.from_env({}).account_labels) == {}


def test_invalid_label_pairs_are_ignored_with_a_warning_that_omits_the_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = "secret.person@example.edu,no-at=Label,bob@example.com=,=Label,ok@example.com=Fine"
    with caplog.at_level(logging.WARNING, logger="agent.config"):
        s = Settings.from_env({"PERSONALAI_ACCOUNT_LABELS": raw})
    assert dict(s.account_labels) == {"ok@example.com": "Fine"}
    assert "ignored 4 invalid entries" in caplog.text
    assert "secret.person" not in caplog.text and "example" not in caplog.text


def test_overlong_label_is_invalid() -> None:
    s = Settings.from_env({"PERSONALAI_ACCOUNT_LABELS": f"a@example.com={'x' * 41}"})
    assert dict(s.account_labels) == {}


@pytest.mark.parametrize(
    "domain",
    ["gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"],
)
def test_consumer_domains_show_the_full_address(domain: str) -> None:
    assert account_label(Settings(), f"Someone@{domain.upper()}") == f"someone@{domain}"


@pytest.mark.parametrize(
    ("account", "label"),
    [
        ("someone@cs.example.edu", "Example"),
        ("someone@example.org", "Example"),
        ("someone@mail.example.edu.au", "Example"),
        ("someone@example.edu.au", "Example"),
        ("someone@localhost", "Localhost"),
        ("not-an-address", "not-an-address"),
    ],
)
def test_other_domains_show_the_second_level_name(account: str, label: str) -> None:
    assert account_label(Settings(), account) == label


def test_a_configured_label_wins_case_insensitively() -> None:
    s = Settings(account_labels={"college@example.edu": "College"})
    assert account_label(s, "College@Example.EDU") == "College"
    assert account_label(s, "other@example.edu") == "Example"


# --- GET /accounts -----------------------------------------------------------------------------


def _with_accounts(api: NotifyApi, **changes: object) -> None:
    api.client.app.state.settings = replace(api.env.settings, **changes)  # type: ignore[attr-defined]


def test_accounts_requires_the_device_token() -> None:
    api = _api()
    assert api.client.get("/accounts").status_code == 401
    assert api.client.get("/accounts", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_accounts_lists_every_google_account_with_label_and_kinds() -> None:
    api = _api()
    _with_accounts(
        api,
        mail_accounts=("me@example.com", "Study@Example.edu"),
        calendar_accounts=("me@example.com",),
        classroom_accounts=("study@example.edu",),
        drive_accounts=("drive@example.org", "me@example.com"),
        account_labels={"study@example.edu": "College"},
    )
    assert _get(api, "/accounts") == {
        "accounts": [
            {
                "account": "me@example.com",
                "label": "Example",
                "kinds": ["mail", "calendar", "drive"],
            },
            {"account": "study@example.edu", "label": "College", "kinds": ["mail", "classroom"]},
            {"account": "drive@example.org", "label": "Example", "kinds": ["drive"]},
        ]
    }


def test_accounts_is_empty_when_nothing_is_configured() -> None:
    api = _api()
    _with_accounts(
        api, mail_accounts=(), calendar_accounts=(), classroom_accounts=(), drive_accounts=()
    )
    assert _get(api, "/accounts") == {"accounts": []}
