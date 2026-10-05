# Security model

PersonalAi is a private agent with read access to mail, calendar, files and finances. This document lists what it protects, who it defends against, and which code enforces each defence. The binding rules live in `CLAUDE.md`.

## Assets

- Mail, calendar, Classroom, Drive and local file contents.
- Bank SMS, ledger rows and Groww holdings.
- Personal identifiers: PAN, Aadhaar, card and account numbers, UPI IDs, phone numbers, OTPs and passwords.
- Secrets: the device tokens, the per-device approval keys, the NVIDIA API key, OAuth refresh tokens and the database key.
- The ability to cause side effects (send mail, change calendar, share files).

## Adversaries and mitigations

| Adversary | Mitigation | Code |
|---|---|---|
| Network attacker | The server binds only to loopback or Tailscale addresses. Each configured address is parsed with `ipaddress` and checked against `127.0.0.0/8`, `::1/128`, `100.64.0.0/10` and `fd7a:115c:a1e0::/48`. `0.0.0.0`, `::`, LAN IPs, hostnames and scoped addresses are refused at startup. Every route except `POST /pair` needs a device bearer token. API docs are disabled. | `agent/core/netguard.py`, `agent/main.py`, `agent/api/auth.py`, `agent/api/app.py` |
| Malicious LAN host | Same as above: the service is not reachable on LAN interfaces. Pairing works only during a short window opened from the laptop (`pair` command), is single use, and closes after 5 wrong codes. Failures all return the same 403. | `agent/api/pair.py` |
| Prompt injection via mail, files, SMS or Classroom | Untrusted tool output is wrapped in `<untrusted_data>` tags (and the tags inside it are neutralised), and the system prompt says it is data. More importantly, the model cannot execute anything with side effects: every WRITE tool call only creates a pending action. v1 has no arbitrary-URL fetch tool. | `agent/core/loop.py`, `agent/core/tools.py`, `agent/core/approvals.py` |
| Model or loop bug trying to write directly | The registry has no method that runs a WRITE tool. The only way to get an executor is `executor_for_approved`, used by `ApprovalEngine` after a verified approval. Tool names that look like broker order APIs are refused at registration. | `agent/core/tools.py`, `agent/core/policy.py` |
| Stolen unlocked device token | The token alone can never approve. An approval needs an HMAC made with the approval key, which the phone can only read after a biometric unlock. See the signature scheme below. | `agent/core/policy.py`, `agent/core/approvals.py` |
| Stolen phone (locked) | The approval key is stored with `requireAuthentication: true` in `expo-secure-store`, so it is unreadable without the owner's biometrics. A device can be revoked on the laptop (`devices.revoked`). | `agent/api/auth.py`, `agent/api/pair.py` |
| Replay or tampering of an approval | The signature covers action id, payload hash, one-time nonce and decision. The server recomputes the payload hash from the stored payload, compares in constant time, updates status with `WHERE status = 'pending' AND nonce = ?` inside one transaction, and refuses actions older than 15 minutes. The executor runs with the stored payload, never the request. | `agent/core/policy.py`, `agent/core/approvals.py` |
| Sensitive data reaching the cloud LLM | Every string sent to the model is a `Redacted` value that only `agent/core/redact.py` can create. The LLM client refuses anything else at runtime, before any HTTP request. Tool results are redacted before serialisation, including numeric account numbers. Placeholders are stable per conversation and rehydrated locally. Input cannot forge a placeholder (`⟨`/`⟩` are neutralised). | `agent/core/redact.py`, `agent/core/llm.py` |
| Stolen disk or database file | Message bodies, redaction maps, action payloads, previews and results are AES-256-GCM encrypted per column, with the table, column and row id as associated data so ciphertexts cannot be swapped. The key is in the OS keyring. | `agent/store/crypto.py`, `agent/store/db.py` |
| Plaintext secrets | Secrets live only in the OS keyring. Startup refuses a fail, null or plaintext backend; only an allowlist of OS-backed backends is accepted. Settings never read secrets from the environment. | `agent/store/keystore.py`, `agent/config.py` |
| Tampering with the audit trail | The audit log is append-only (SQL triggers abort UPDATE and DELETE) and hash-chained, so a modified or inserted row fails `verify()`. Entries carry short codes, never payloads or PII. | `agent/store/db.py`, `agent/core/audit.py` |
| Log or notification leakage | Logs carry ids, counts and exception type names only. Push notifications (M5) carry no content. | all modules |
| Repo leakage (the repo is public) | `.gitignore` excludes `.env`, `*.db` and token files. Test fixtures are synthetic (example.com, made-up numbers). gitleaks runs in CI. Tests use an in-memory keyring and never touch a real one. | `.gitignore`, `tests/conftest.py`, CI |

## Approval signature scheme

At pairing the server creates a 32-byte random approval key for the device, stores it in the keyring under `approval_key:{device_id}`, and returns it once (base64url, no padding). The phone keeps it in `expo-secure-store` with `requireAuthentication: true`.

To approve or reject an action the phone sends `POST /approvals/{id}/approve` or `/reject` with the device bearer token and:

```json
{"payload_hash": "<hex sha256>", "nonce": "<nonce>", "sig": "<64 lowercase hex>"}
```

where

```
sig = hex(HMAC-SHA256(approval_key, f"{action_id}|{payload_hash}|{nonce}|{decision}"))
```

and `decision` is `approve` or `reject` (it comes from the path). `payload_hash` is the SHA-256 hex of `json.dumps({"tool": name, "args": args}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8. The phone reads `payload_hash` and `nonce` from `GET /approvals`.

The server accepts only if all of these hold: the decision is valid; the action is still pending; it is at most 15 minutes old (and not more than 30 seconds in the future); the stored payload still hashes to the stored hash; the request hash and nonce match the stored ones; and the signature is 64 lowercase hex characters equal to the expected value. All comparisons use `hmac.compare_digest`. Failures return a short reason code and are audited as `approval_denied`.

## Mail (M2)

- **Scope.** The Gmail connector uses `https://www.googleapis.com/auth/gmail.modify`. That scope does permit sending mail, so the protection is in the code: the agent has no send tool and nothing calls `messages.send` or `drafts.send`, and a test (`tests/test_gmail_google.py`) fails if any code under `agent/` does. Mail changes are limited to archive, label and trash.
- **Trash, not delete.** `mail_trash` moves messages to Gmail's trash, which is recoverable. No tool performs a permanent delete, and the tools carry no such name or code path.
- **Writes need approval.** `mail_archive`, `mail_trash` and `mail_label` are WRITE tools. A model call only creates a pending action whose preview lists every message (sender, subject, account). The executor runs after a signed approval and re-validates the stored payload (item shape, at most 100 items, label allowlist) before touching Gmail.
- **Prompt injection can only mis-rank, not act.** Mail is untrusted data. The worst an injected mail can do is influence its own category or make the model propose a write, which still needs the owner's biometric approval. The classifier has no tools. Category feedback (`POST /mail/feedback`) is a human-only endpoint; no tool exposes it.
- **Classifier is local.** Mail is classified by rules, then by the local Ollama model (`PERSONALAI_CLASSIFIER_MODEL`). The classifier URL must be a loopback IP literal; the NVIDIA endpoint is never used for classification. Text sent to it is still redacted and wrapped as untrusted.
- **Encrypted at rest.** Sender, recipients, subject, snippet, body and the model's free-text reason are AES-256-GCM encrypted per column, with the table, column, account and message id as associated data. The only sender index is a keyed hash (`HMAC-SHA256`, with a subkey derived from the database key), so addresses cannot be recovered from the file and the hash cannot be recomputed without the key.
- **Credentials.** The OAuth client and each account's refresh token are stored only in the OS keyring. Refreshed tokens are written back to the keyring, never to disk. Long secrets are split across several keyring entries (the Windows store rejects values over about 1280 characters) and verified with a sha256 check on read; a missing or altered chunk is an error, never a silent partial value.
- **Google credentials.** Each Google account has one token in the keyring, shared by every Google connector. Scopes are added incrementally by `scripts/setup_google_oauth.py` and kept on re-runs: `gmail.modify`, `calendar.events`, the Classroom read-only scopes (`classroom.courses.readonly`, `classroom.coursework.me.readonly`, `classroom.announcements.readonly`, `classroom.courseworkmaterials.readonly`), `drive.readonly` and `drive.file`. `drive.file` lets the app write only files it created itself. A connector refuses to run if the token lacks the scope it needs.
- **Logs.** Sync logs carry message ids, counts and exception type names only. Accounts are logged by position, never by address.

## Calendar, Classroom, Drive and local files (M3)

- **Writes need approval.** `calendar_create_event`, `calendar_update_event`, `calendar_add_deadline` and `drive_create_text_file` are WRITE tools. Their previews show everything that will be written (title, times, location, full description or file content). Calendar writes always use `sendUpdates=none` and never set attendees, conference data or extended properties chosen by the model, so an event cannot invite or email anyone. Titles and other one-line fields reject control and bidi characters so they cannot fake extra lines in the preview.
- **Classroom is read-only.** Only read-only Classroom scopes are requested and the connector has no create, patch or turn-in calls. Upcoming deadlines are turned into *proposed* `calendar_add_deadline` actions by a background job; nothing reaches the calendar until the owner approves. A rejected deadline is never proposed again; an expired one is re-proposed at most once a day, or when the teacher changes the due date. The job leaves at least half of the pending-action limit free for chat.
- **Drive.** `drive.readonly` for reading and `drive.file` for creating; the app can only modify files it created. There is no share, permission, update or delete tool. Search queries are escaped and always exclude trashed files.
- **Local files are read-only and allowlisted.** Only folders in `PERSONALAI_FILE_ROOTS` are readable. Every path is resolved (symlinks included) and must stay inside a root; hidden files and folders, unsupported types and files over 20 MB are refused. The indexer does not follow symlinks or junctions. There is no file-write tool.
- **The search index holds no plaintext.** Words are indexed in SQLite FTS5 as keyed hashes (`HMAC-SHA256` with a subkey of the database key, truncated to 64 bits), and file paths are AES-GCM encrypted. Searching needs the key; someone with only the database file sees which hashed words occur together and how often, but not the words or file names. Text is re-read from disk when a file is opened.
- **Untrusted content.** Event descriptions, Classroom posts, Drive files and local files are returned to the model inside `<untrusted_data>` and pass through redaction like mail.
- **Background jobs** log only job names, counts and exception type names, since exception text can carry paths or addresses.

## Known limits

- Anything the owner approves is trusted. The approval preview must show the full content (recipients, text) so the owner can spot an injected action.
- Redaction is pattern-based and deliberately over-redacts; free-text names and addresses are not masked.
- The pairing code and device token travel over the Tailscale tunnel; protect the laptop session itself.
