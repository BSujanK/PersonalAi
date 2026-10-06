"""Wiring for Calendar, Classroom, Drive and local files, shared by the entry point and tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.config import Settings
from agent.connectors.accounts import cached_factory
from agent.connectors.classroom import ClassroomApi
from agent.connectors.classroom_google import build_classroom_api
from agent.connectors.drive import DriveApi
from agent.connectors.drive_google import build_drive_api
from agent.connectors.files import FileIndex, FileRoots
from agent.connectors.gcal_google import build_calendar_api
from agent.connectors.google_auth import GoogleAuth
from agent.core.clock import Clock
from agent.core.tools import ToolRegistry
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.workspace.calendar_tools import register_calendar_tools
from agent.workspace.classroom_tools import register_classroom_tools
from agent.workspace.deadlines import register_deadline_tool
from agent.workspace.drive_tools import register_drive_tools
from agent.workspace.file_tools import register_file_tools


@dataclass(frozen=True)
class WorkspaceServices:
    classroom_api_for: Callable[[str], ClassroomApi] | None
    file_index: FileIndex | None
    drive_api_for: Callable[[str], DriveApi] | None = None
    file_roots: FileRoots | None = None


def validate_workspace_settings(settings: Settings) -> None:
    deadline = settings.deadline_calendar_account
    if deadline is not None and deadline not in settings.calendar_accounts:
        raise ValueError("PERSONALAI_DEADLINE_CALENDAR must be one of the calendar accounts")


def setup_workspace(
    settings: Settings,
    db: Database,
    db_key: bytes,
    registry: ToolRegistry,
    auth: GoogleAuth,
    clock: Clock,
) -> WorkspaceServices:
    """Register the M3 tools for every configured service. Raises ``ValueError`` on bad config."""
    validate_workspace_settings(settings)
    if settings.calendar_accounts:
        calendar_for = cached_factory(
            settings.calendar_accounts, lambda a: build_calendar_api(a, auth)
        )
        register_calendar_tools(registry, calendar_for, settings.calendar_accounts, clock)
        register_deadline_tool(registry, calendar_for, settings.calendar_accounts)
    classroom_for: Callable[[str], ClassroomApi] | None = None
    if settings.classroom_accounts:
        classroom_for = cached_factory(
            settings.classroom_accounts, lambda a: build_classroom_api(a, auth)
        )
        register_classroom_tools(registry, classroom_for, settings.classroom_accounts, clock)
    drive_for: Callable[[str], DriveApi] | None = None
    if settings.drive_accounts:
        drive_for = cached_factory(settings.drive_accounts, lambda a: build_drive_api(a, auth))
        register_drive_tools(registry, drive_for, list(settings.drive_accounts))
    file_index: FileIndex | None = None
    roots: FileRoots | None = None
    if settings.file_roots:
        roots = FileRoots(settings.file_roots)
        file_index = FileIndex(db, FieldCipher(db_key), db_key, roots, clock)
        register_file_tools(registry, file_index, roots)
    return WorkspaceServices(classroom_for, file_index, drive_for, roots)
