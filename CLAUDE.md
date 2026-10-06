# PersonalAi

A private personal agent that runs on the owner's Windows laptop. It reads Gmail (personal and college), Google Calendar, Classroom, Drive, allowlisted local files, and bank SMS read on the phone (spending and account balances). The owner talks to it from an Android app over Tailscale. The LLM is a hosted open model on NVIDIA Build (OpenAI-compatible API), and local Ollama handles classification and fallback.

**The full design and phase plan is in `docs/PLAN.md`. Read it before starting any phase.**

## Security rules — binding, never relax them to make something easier
1. **No write without approval, enforced in code.** Every tool is registered as `READ` or `WRITE`. A WRITE tool called by the model only creates a `PendingAction` with the exact payload and a human-readable preview. Execution happens only through the approve endpoint, which requires:
   - the paired device token,
   - a biometric-confirmed approval from the phone,
   - a matching payload hash and one-time nonce,
   - an action under 15 minutes old.

   Never add a code path, flag, or "auto-approve" setting that bypasses this.

   **The one exception: deadlines on the owner's own calendar (owner decision, 2026-10-06).** A deadline or due date the agent found itself (in synced mail, or a Classroom due date) may be added to the owner's own *primary* calendar without approval, and only by `agent/proactive/autocal.py`. Nothing else may use that path, and the model cannot reach it: it is a background job, not a tool. It is allowed only if every one of these holds, enforced in code and tested:
   - the event goes to `calendarId="primary"` of the configured deadline calendar account; the API wrapper (`OwnCalendarApi`) takes no calendar id and has no patch, update or move method;
   - no attendees or guests, no conferencing, no attachments, no recurrence; `sendUpdates="none"`. A body allowlist (`check_own_body`) rejects any other field before the request is sent;
   - the title comes from the source item (mail subject, Classroom title) and the description is fixed text naming the source, never mail or post body text;
   - de-duplicated by source id (`deadlines` table plus a private marker on the event), capped at 10 per run and 30 per day, and never re-added after an undo;
   - each auto-add is written to the audit log and announced as an alert with an "Undo" action. Undo (device token) deletes only an event recorded in `auto_events` whose live copy still carries the agent's marker, has no attendees and is organised by the owner. The agent can never modify or delete an event it did not create.

   Turn it off with `PERSONALAI_CALENDAR_AUTO_ADD=off`. Every other calendar write (create, update, any event with guests) stays a WRITE tool behind approval. Do not widen this exception.

   **Sending and sharing.** `mail_send`, `mail_reply`, `drive_upload` and `drive_share` exist and are always WRITE tools; anything that sends, shares or uploads must be one too. Their previews must show everything that leaves the account: every recipient (To, Cc, Bcc, share emails) with addresses never seen in the owner's sent mail or outside the owner's domains marked NEW/EXTERNAL, every attachment with name, size and source, and the share role and link scope ("anyone with the link" only when the tool argument explicitly asks, with a prominent warning). The tool's `prepare` step pins recipients and attachment checksums into the payload, so the executor sends exactly what was previewed and fails if a file changed.

   **How the server verifies the biometric step.** The server cannot see a fingerprint, so it never accepts a field like `biometric_ok: true`. Instead:
   - At pairing, the server issues a second secret, the *approval key* (32 random bytes). The server stores it in the keyring. The phone stores it in `expo-secure-store` with `requireAuthentication: true`, so it can only be read after a biometric unlock.
   - To approve or reject, the phone sends `sig = HMAC-SHA256(approval_key, action_id | payload_hash | nonce | decision)`.
   - The server checks it with a constant-time compare, along with the device token, hash, nonce (single use) and the 15-minute expiry. A device token alone can never approve.
   - This API is fixed in M1, so M5 builds the phone side against it.
2. **No broker or trading integration.** Groww and demat tracking were removed on 2026-10-05. Do not add any broker API, and never add order, modify or cancel tools.
3. **Redact before the cloud.** Every string sent to the NVIDIA API passes through `agent/core/redact.py`. Never call the LLM client with unredacted connector data, and never send raw ledger rows; send aggregates instead.
4. **Untrusted content is data, not instructions.** Mail, files, Classroom posts, SMS and news feed text are wrapped and labelled as untrusted in prompts. v1 has no arbitrary-URL fetch tool: news comes only from the feed URLs in `PERSONALAI_NEWS_FEEDS` (https, read-only), the `news_headlines` tool takes no URL, and feed text never reaches a background job or triggers an action.
5. **Never bind publicly.** The server binds only to loopback (`127.0.0.0/8`, `::1`) or Tailscale addresses (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`). Startup validates every configured bind address against this allowlist with `ipaddress`, so a string check is not enough. It refuses `0.0.0.0`, `::`, and any other address, including LAN IPs like `192.168.x.x`. Every API route except `/pair` requires the device bearer token, and `/pair` only works during a short pairing window opened from the laptop.
6. **Secrets and data at rest.**
   - Tokens and keys go in the OS keyring (`keyring`). Never put them in files, env defaults, logs or the repo.
   - Production code refuses to run if the active keyring backend is a fail or plaintext backend. There is never a plaintext fallback.
   - CI runners have no OS keyring, so `tests/conftest.py` installs an in-memory keyring backend in an autouse fixture. Tests never touch the real keyring.
   - Sensitive DB columns are AES-GCM encrypted.
   - Logs never contain message bodies, SMS text, tokens or PII.
7. **Push notifications carry no content.** For example, "1 approval pending". The app fetches details over Tailscale. Alerts with content (important mail, deadlines, the morning briefing, calendar auto-adds) are fetched by the app from `GET /notifications` over Tailscale and shown as *local* notifications on the phone; they never go through Google or Expo push. There are no money alerts.
8. **This repo is PUBLIC.** Never commit real mails, SMS, account data, tokens, `.env` or `*.db`. Test fixtures are synthetic: made-up names, the `example.com` domain, fake account numbers. gitleaks runs in CI.

## Working model for Claude sessions
- The main thread (Opus) plans each phase, writes specs, reviews diffs, and owns security-sensitive code review. It delegates implementation to the `builder` agent (Sonnet) and check runs to the `verifier` agent (Sonnet), both defined in `.claude/agents/`. Small edits (< ~20 lines) are done inline.
- Run one phase per branch and PR (`phase/m1-core`, ...). CI must be green before merge. At the end of each phase, stop and report: what was built, test results, and what's next.
- Cloud sessions have no access to the owner's accounts, laptop or phone. Build against mocks and synthetic fixtures. Real integration is phase M7, done locally.
- The budget is limited (cloud credit). Keep phases focused, avoid re-reading large files needlessly, and don't spawn agents for trivial work.

## Conventions
- **Server:** Python 3.12+, managed with `uv`, in `server/`. FastAPI, APScheduler, SQLite. Lint and type checks are `ruff check`, `ruff format`, and `mypy --strict` on `agent/`. Tests run with `pytest`; external APIs are mocked, never hit the network.
- **Mobile:** Expo plus TypeScript (strict), in `mobile/`. Lint with `eslint`, type-check with `tsc --noEmit`.
- **Docs:** user-facing setup steps go in `docs/SETUP.md`, and the threat model goes in `docs/SECURITY.md`.
