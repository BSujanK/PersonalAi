"""GET /accounts: the configured Google accounts, their labels and what each is used for.

Addresses and labels only: no tokens, no scopes. The app uses it to show which account a mail,
deadline or alert came from."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent.config import Settings, account_label

router = APIRouter()


def _kinds(settings: Settings, account: str) -> list[str]:
    connectors = (
        ("mail", settings.mail_accounts),
        ("calendar", settings.calendar_accounts),
        ("classroom", settings.classroom_accounts),
        ("drive", settings.drive_accounts),
    )
    return [kind for kind, accounts in connectors if account in {a.lower() for a in accounts}]


@router.get("/accounts")
def accounts(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "accounts": [
            {
                "account": account,
                "label": account_label(settings, account),
                "kinds": _kinds(settings, account),
            }
            for account in settings.google_accounts
        ]
    }
