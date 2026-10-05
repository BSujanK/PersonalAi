# Security model

PersonalAi is a private agent with read access to mail, calendar, files and finances. This document lists what it protects, who it defends against, and which code enforces each defence. The binding rules live in `CLAUDE.md`.

## Assets

- Mail, calendar, Classroom, Drive and local file contents.
- Bank SMS, bank alert mail, ledger rows and account balances.
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
| Finance data | Bank SMS arrive only from the paired phone (`POST /sms`, device token). Non-bank senders and anything that looks like an OTP or PIN are dropped with no body or sender kept; only an idempotency hash is stored. Amounts, balances, counterparties and masked accounts are AES-GCM encrypted per row; accounts, counterparties and references are indexed by keyed HMAC. The LLM tools `spend_summary`, `balances` and `transactions` return aggregates only (totals, counts, groups, day-level dates), never rows, references or raw SMS. The local categoriser sends Ollama only the redacted counterparty, direction and channel. | `agent/finance/`, `agent/api/finance.py` |
| Forged bank alert mail | Alert mails are read only from known bank domains (exact or subdomain match) and never from SPAM or TRASH. A forged mail that passes Gmail's filters could still add a ledger row, or set a balance until the next bank SMS replaces it. Email-only rows are marked as such (`from_email`) so the app can show where a figure came from. | `agent/finance/email_alerts.py`, `agent/finance/ingest.py` |
| Log or notification leakage | Logs carry ids, counts and exception type names only. Push notifications carry only a count ("1 approval pending") and are off unless `PERSONALAI_PUSH=expo`; the app then fetches details over Tailscale. | all modules, `agent/phone/push.py` |
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

## Phone app and phone actions (M5)

- **Pairing.** `python -m agent pair` prints a terminal QR of `{"v":1,"url","code"}`, where the URL is the first Tailscale bind address (or `--url`). The app accepts only Tailscale hosts (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`, `*.ts.net`), so a forged QR cannot point it, or its bank SMS, at another server (`mobile/src/lib/serverUrl.ts`).
- **Secrets on the phone.** The device token is in `expo-secure-store` (Android Keystore, this device only). The approval key is stored with `requireAuthentication: true`; pairing refuses to finish if biometrics are not available, and there is no unauthenticated fallback. The key is read once per decision, used to sign, and zeroed (`mobile/src/lib/secureKeys.ts`). The app blocks Android backups.
- **Signing.** `mobile/src/lib/approvalSignature.ts` builds the same message as `policy.signature_message` and signs it with `@noble/hashes`. `shared/test-vectors/approval-signature.json` is checked by both the server and the app tests, so the two sides cannot drift.
- **Phone actions.** `phone_set_alarm`, `phone_set_timer` and `phone_reminder` are WRITE tools. Their executor only queues a command (parameters AES-GCM encrypted); the app fetches queued commands, validates them again, and fires `SET_ALARM`/`SET_TIMER` intents or a local notification. Commands expire (alarms after 24 hours, timers when they would have rung, reminders at their time) and can be acknowledged once.
- **Bank SMS.** The phone filters by bank sender ID before anything is stored or sent; other SMS never leave the native receiver. Filtered SMS wait in an app-private queue until `POST /sms` succeeds.
- **Push.** Expo's push service sees only the device push token and the count text. Push tokens live in the server keyring.

## Known limits

- Anything the owner approves is trusted. The approval preview must show the full content (recipients, text) so the owner can spot an injected action.
- Redaction is pattern-based and deliberately over-redacts; free-text names and addresses are not masked.
- The pairing code and device token travel over the Tailscale tunnel; protect the laptop session itself.
- The app talks plain HTTP inside the Tailscale (WireGuard) tunnel, so Android cleartext traffic is enabled; the host check above limits it to Tailscale peers.
- A pairing whose biometric step is cancelled leaves an unused device row on the server; it has no stored approval key on the phone and can be revoked.
