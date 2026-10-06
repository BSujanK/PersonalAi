"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from agent.api import approvals as approvals_routes
from agent.api import chat as chat_routes
from agent.api import conversations as conversations_routes
from agent.api import device as device_routes
from agent.api import files as files_routes
from agent.api import finance as finance_routes
from agent.api import mail as mail_routes
from agent.api import pair as pair_routes
from agent.api import today as today_routes
from agent.api.auth import require_device
from agent.api.limits import BodySizeLimit
from agent.config import Settings
from agent.core.approvals import ApprovalEngine
from agent.core.audit import AuditLog
from agent.core.clock import Clock, utcnow
from agent.core.llm import LLMClient
from agent.core.locks import KeyedLocks
from agent.core.loop import AgentLoop
from agent.core.redact import Redactor
from agent.core.tools import ToolRegistry
from agent.finance.services import FinanceServices
from agent.mail.services import MailServices
from agent.phone.commands import CommandQueue
from agent.phone.push import PushNotifier
from agent.phone.tools import register_phone_tools
from agent.store.crypto import FieldCipher
from agent.store.db import Database
from agent.store.keystore import KeyStore


def create_app(
    settings: Settings,
    *,
    db: Database,
    keystore: KeyStore,
    llm: LLMClient,
    registry: ToolRegistry,
    clock: Clock = utcnow,
    mail: MailServices | None = None,
    finance: FinanceServices | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodySizeLimit)
    cipher = FieldCipher(keystore.get_or_create_bytes("db_key"))
    audit = AuditLog(db, clock)
    approvals = ApprovalEngine(
        db,
        cipher,
        registry,
        audit,
        keystore,
        clock,
        on_proposed=lambda: app.state.push.notify_pending(approvals.pending_count()),
    )
    commands = CommandQueue(db, cipher, clock)
    register_phone_tools(registry, commands, clock)
    redactor = Redactor(settings.redaction_emails)
    app.state.settings = settings
    app.state.db = db
    app.state.keystore = keystore
    app.state.clock = clock
    app.state.cipher = cipher
    app.state.audit = audit
    app.state.approvals = approvals
    app.state.registry = registry
    app.state.commands = commands
    app.state.push = PushNotifier(db, keystore, enabled=settings.push == "expo")
    app.state.chat_locks = KeyedLocks()
    app.state.loop = AgentLoop(llm, registry, redactor, approvals, settings, clock)

    # /pair is the only route without the device-token dependency.
    app.include_router(pair_routes.router)
    protected = [Depends(require_device)]
    app.include_router(chat_routes.router, dependencies=protected)
    app.include_router(conversations_routes.router, dependencies=protected)
    app.include_router(approvals_routes.router, dependencies=protected)
    app.include_router(device_routes.router, dependencies=protected)
    app.include_router(today_routes.router, dependencies=protected)
    app.include_router(files_routes.router, dependencies=protected)
    if mail is not None:
        app.state.mail = mail
        app.include_router(mail_routes.router, dependencies=protected)
    if finance is not None:
        app.state.finance = finance
        app.include_router(finance_routes.router, dependencies=protected)

    health = APIRouter(dependencies=protected)

    @health.get("/health")
    def get_health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(health)
    return app
