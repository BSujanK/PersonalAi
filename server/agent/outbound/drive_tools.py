"""drive_upload and drive_share (approval-gated WRITE tools); the only callers of DriveApi.share."""

from __future__ import annotations

from typing import Any

from agent.core.tools import ActionRejected, Tool, ToolKind, ToolRegistry
from agent.outbound.attachments import (
    FOLDER_MIME,
    Sources,
    check_drive_account,
    check_file_id,
    drive_metadata,
    human_size,
    load_attachment,
    local_entry,
    resolve_local,
)
from agent.outbound.recipients import (
    MAX_RECIPIENTS,
    RecipientPolicy,
    check_addresses,
    display,
    flags,
    warning_lines,
)

ROLES = {"reader": "Viewer", "commenter": "Commenter", "writer": "Editor"}
_LINK_ROLES = ("reader", "commenter")
ANYONE_WARNING = (
    "⚠⚠ WARNING: ANYONE WITH THE LINK will be able to open this file. The link works for "
    "people outside your accounts, without signing in as anyone you know, and can be "
    "forwarded to anyone."
)


def upload_preview(payload: dict[str, Any]) -> str:
    folder = (
        f"{display(payload['folder_name'])} (id {payload['folder_id']})"
        if payload["folder_id"]
        else "My Drive (top level)"
    )
    return "\n".join(
        [
            "Upload a local file to Google Drive",
            f"Account: {payload['account']}",
            f"File: {display(payload['name'])} — {human_size(payload['size'])} — {payload['mime']}",
            f"From: {display(payload['path'], 400)}",
            f"To folder: {folder}",
            "The uploaded file stays private to you; nothing is shared.",
        ]
    )


def share_preview(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    if payload["anyone_with_link"]:
        lines.append(ANYONE_WARNING)
    lines += warning_lines(payload["people"])
    lines += [
        "Share a Google Drive file",
        f"Account: {payload['account']}",
        f"File: {display(payload['name'])} ({payload['mime']}, id {payload['file_id']})",
        f"Access: {ROLES[payload['role']]} ({payload['role']})",
    ]
    if payload["people"]:
        lines.append("People:")
        lines += [f"  • {p['addr']}  {flags(p)}" for p in payload["people"]]
    else:
        lines.append("People: (none)")
    if payload["anyone_with_link"]:
        lines.append(f"Link sharing: ON — anyone with the link ({ROLES[payload['role']]})")
    else:
        lines.append("Link sharing: off — only the people above can open it")
    if payload["people"]:
        lines.append(
            "Google emails each person a notification."
            if payload["notify"]
            else "No notification email is sent."
        )
    return "\n".join(lines)


def register_drive_action_tools(
    registry: ToolRegistry, policy: RecipientPolicy, sources: Sources
) -> None:
    def upload_prepare(args: dict[str, Any]) -> dict[str, Any]:
        account = check_drive_account(args.get("account"), sources)
        path, data = resolve_local(args.get("path"), sources)
        folder_id = args.get("folder_id")
        folder_name = ""
        if folder_id is not None:
            folder_id = check_file_id(folder_id)
            meta = drive_metadata(account, folder_id, sources)
            if meta.get("mimeType") != FOLDER_MIME:
                raise ActionRejected("folder_id is not a Drive folder")
            folder_name = str(meta.get("name", ""))
        entry = local_entry(path, data)
        return {
            "account": account,
            **{k: entry[k] for k in ("path", "name", "size", "mime", "sha256")},
            "folder_id": folder_id,
            "folder_name": folder_name,
        }

    def upload_run(payload: dict[str, Any]) -> Any:
        data = load_attachment({"source": "local", **payload}, sources)
        assert sources.drive_for is not None  # noqa: S101 - prepare required Drive
        created = sources.drive_for(payload["account"]).create_file(
            payload["name"], payload["mime"], data, payload["folder_id"]
        )
        return {
            "id": created.get("id"),
            "name": created.get("name"),
            "link": created.get("webViewLink"),
        }

    def share_prepare(args: dict[str, Any]) -> dict[str, Any]:
        account = check_drive_account(args.get("account"), sources)
        file_id = check_file_id(args.get("file_id"))
        emails = check_addresses(args.get("emails"), "emails")
        role = args.get("role", "reader")
        if role not in ROLES:
            raise ActionRejected("role must be reader, commenter or writer")
        anyone = args.get("anyone_with_link", False)
        notify = args.get("notify", True)
        if not isinstance(anyone, bool) or not isinstance(notify, bool):
            raise ActionRejected("anyone_with_link and notify must be true or false")
        if not emails and not anyone:
            raise ActionRejected("give the email addresses to share with")
        if anyone and role not in _LINK_ROLES:
            raise ActionRejected("a link for anyone can only give reader or commenter access")
        meta = drive_metadata(account, file_id, sources)
        return {
            "account": account,
            "file_id": file_id,
            "name": str(meta.get("name", file_id)),
            "mime": str(meta.get("mimeType", "")),
            "role": role,
            "people": [policy.classify(e, "People") for e in emails],
            "anyone_with_link": anyone,
            "notify": notify,
        }

    def share_run(payload: dict[str, Any]) -> Any:
        assert sources.drive_for is not None  # noqa: S101 - prepare required Drive
        api = sources.drive_for(payload["account"])
        role = payload["role"]
        for person in payload["people"]:
            api.share(
                payload["file_id"],
                {"type": "user", "role": role, "emailAddress": person["addr"]},
                payload["notify"],
            )
        if payload["anyone_with_link"]:
            api.share(
                payload["file_id"],
                {"type": "anyone", "role": role, "allowFileDiscovery": False},
                False,
            )
        meta = api.get_metadata(payload["file_id"])
        return {
            "file_id": payload["file_id"],
            "link": meta.get("webViewLink"),
            "shared_with": [p["addr"] for p in payload["people"]],
            "anyone_with_link": payload["anyone_with_link"],
            "role": role,
        }

    account_schema = {"type": "string", "description": "The Drive account (from drive_search)."}
    registry.register(
        Tool(
            name="drive_upload",
            description=(
                "Propose uploading one local file (a path from files_search) to the owner's "
                "Google Drive, optionally into a folder. The file stays private. Requires the "
                "owner's approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": account_schema,
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "folder_id": {
                        "type": "string",
                        "description": "Drive folder id from drive_search; leave out for My Drive.",
                    },
                },
                "required": ["account", "path"],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=upload_run,
            preview=upload_preview,
            prepare=upload_prepare,
        )
    )
    registry.register(
        Tool(
            name="drive_share",
            description=(
                "Propose sharing one Drive file (an id from drive_search) with specific people. "
                "Default access is reader. Set anyone_with_link only when the owner explicitly "
                "asked for a public link. Requires the owner's approval; the link is shown to "
                "the owner after approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "account": account_schema,
                    "file_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
                    "emails": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_RECIPIENTS,
                        "description": "Plain email addresses to share with.",
                    },
                    "role": {"type": "string", "enum": list(ROLES)},
                    "anyone_with_link": {
                        "type": "boolean",
                        "description": "Anyone with the link can open it. Default false.",
                    },
                    "notify": {
                        "type": "boolean",
                        "description": "Google emails each person (default true).",
                    },
                },
                "required": ["account", "file_id"],
                "additionalProperties": False,
            },
            kind=ToolKind.WRITE,
            run=share_run,
            preview=share_preview,
            prepare=share_prepare,
        )
    )
