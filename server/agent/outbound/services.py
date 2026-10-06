"""Wiring for the outbound WRITE tools, shared by the entry point and tests."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from agent.config import Settings
from agent.connectors.files import FileRoots
from agent.core.tools import ToolRegistry
from agent.mail.services import ApiFor, MailServices
from agent.mail.store import MailStore
from agent.outbound.attachments import DriveApiFor, Sources
from agent.outbound.drive_tools import register_drive_action_tools
from agent.outbound.mail_tools import register_mail_send_tools
from agent.outbound.recipients import RecipientPolicy, SentLookup, check_address

log = logging.getLogger(__name__)


def sent_lookup(store: MailStore, api_for: ApiFor, accounts: Sequence[str]) -> SentLookup:
    """Has the owner ever mailed ``addr``? Synced sent mail first, then Gmail's own search.

    Local sync covers only recent mail, so a miss asks each account's Sent folder. The query
    goes to the owner's own Gmail, never to the LLM.
    """

    def seen(addr: str) -> bool:
        addr = check_address(addr)  # validated, so it is safe inside the search query
        if store.sent_to_any(addr):
            return True
        for account in accounts:
            try:
                ids, _ = api_for(account).list_message_ids(f'in:sent to:"{addr}"', None)
            except Exception as exc:
                log.warning("sent-mail lookup failed: %s", type(exc).__name__)
                continue
            if ids:
                return True
        return False

    return seen


def register_outbound_tools(
    registry: ToolRegistry,
    settings: Settings,
    mail: MailServices | None,
    drive_for: DriveApiFor | None,
    roots: FileRoots | None,
) -> None:
    """mail_send/mail_reply when mail is configured; drive_upload/drive_share with Drive."""
    lookup = (
        sent_lookup(mail.store, mail.api_for, settings.mail_accounts) if mail is not None else None
    )
    policy = RecipientPolicy.from_settings(settings, lookup)
    sources = Sources(
        roots=roots,
        drive_for=drive_for,
        drive_accounts=tuple(settings.drive_accounts) if drive_for is not None else (),
    )
    if mail is not None and settings.mail_accounts:
        register_mail_send_tools(
            registry, mail.store, mail.api_for, settings.mail_accounts, policy, sources
        )
    if drive_for is not None and settings.drive_accounts:
        register_drive_action_tools(registry, policy, sources)
