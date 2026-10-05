# Setup

## Development (any machine)

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
cd server
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy agent
uv run pytest -q
```

Tests mock every external API and use an in-memory keyring, so they need no network, accounts or OS keyring.

## Laptop setup (M7)

Placeholder checklist; the steps are filled in during phase M7, done on the laptop:

- [ ] Install Tailscale and note the laptop's Tailscale IP (`100.x.y.z`).
- [ ] Install Python 3.12+ and `uv`; run `uv sync` in `server/`.
- [ ] Confirm the Windows Credential Manager keyring is active (the server refuses to start otherwise).
- [ ] Store the NVIDIA API key in the keyring under service `PersonalAi`, name `nvidia_api_key`.
- [ ] Install Ollama and pull the local model (`qwen2.5:3b`).
- [ ] Set `PERSONALAI_BIND_HOSTS` to `127.0.0.1,<tailscale ip>` and `PERSONALAI_OWNER_EMAILS` to your addresses.
- [ ] Start with `uv run python -m agent serve`.
- [ ] Pair the phone: `uv run python scripts/pair_phone.py`, then scan or enter the code in the app within 5 minutes.
- [ ] Google OAuth, Groww and SMS forwarding setup (later phases).

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `PERSONALAI_BIND_HOSTS` | Comma-separated bind IPs (loopback or Tailscale only) | `127.0.0.1` |
| `PERSONALAI_PORT` | Port | `8765` |
| `PERSONALAI_DB_PATH` | SQLite file | `~/.personalai/agent.db` |
| `PERSONALAI_NVIDIA_MODEL` | Model id on NVIDIA Build | `meta/llama-3.3-70b-instruct` |
| `PERSONALAI_OWNER_EMAILS` | Your addresses, masked before the cloud | none |
| `PERSONALAI_MAIL_ACCOUNTS` | Comma-separated Gmail addresses to sync (empty turns mail off); also masked before the cloud | none |
| `PERSONALAI_VIP_SENDERS` | Comma-separated senders always classified important | none |
| `PERSONALAI_COLLEGE_DOMAINS` | Comma-separated college domains (subdomains match); mail from them is important | none |
| `PERSONALAI_MAIL_POLL_MINUTES` | Mail sync interval | `5` |
| `PERSONALAI_MAIL_INITIAL_DAYS` | How many days of mail the first sync fetches | `7` |
| `PERSONALAI_CLASSIFIER_MODEL` | Local Ollama model for classification | `qwen2.5:3b` |
| `PERSONALAI_CALENDAR_ACCOUNTS` | Comma-separated Google accounts whose primary calendar the agent reads and proposes changes to | none |
| `PERSONALAI_CLASSROOM_ACCOUNTS` | Comma-separated Google accounts to read Classroom from | none |
| `PERSONALAI_DRIVE_ACCOUNTS` | Comma-separated Google accounts to search and read Drive from | none |
| `PERSONALAI_DEADLINE_CALENDAR` | Calendar account that receives proposed Classroom deadlines | first calendar account |
| `PERSONALAI_DEADLINE_POLL_MINUTES` | How often Classroom is checked for new deadlines | `60` |
| `PERSONALAI_DEADLINE_HORIZON_DAYS` | How far ahead deadlines are proposed | `14` |
| `PERSONALAI_FILE_ROOTS` | Absolute folders the agent may read, separated by `;` on Windows (`:` elsewhere) | none |
| `PERSONALAI_FILE_INDEX_MINUTES` | Local file index refresh interval | `30` |

Secrets are never read from the environment; they live in the OS keyring.

## Mail (M2, finish on the laptop in M7)

1. In Google Cloud, create an OAuth client of type "Desktop app", enable the Gmail, Google Calendar, Classroom and Drive APIs, and download the client JSON.
2. For each account run `uv run python scripts/setup_google_oauth.py --account you@example.com --services gmail --client-secret CLIENT_SECRET.json` from `server/`. A browser opens on `127.0.0.1`; sign in as that account and allow the scopes. The client JSON and the account's token go to the OS keyring, and only the account address and the authorised services are printed. Delete the downloaded JSON afterwards.
3. To add services later, re-run with `--services gmail,calendar,classroom,drive` (any subset). Scopes already granted are kept, and `--client-secret` is only needed the first time.
4. Set `PERSONALAI_MAIL_ACCOUNTS` (and the VIP and college variables) and restart the server. Mail is synced every `PERSONALAI_MAIL_POLL_MINUTES` minutes, starting at launch.
5. Pull a local model for classification, for example `ollama pull qwen2.5:3b`.

## Calendar, Classroom, Drive and local files (M3, finish on the laptop in M7)

1. Authorise the services per account, for example `uv run python scripts/setup_google_oauth.py --account you@example.com --services calendar,drive` and `--account you@college.example.edu --services gmail,classroom,drive`. Earlier scopes are kept.
2. Set `PERSONALAI_CALENDAR_ACCOUNTS`, `PERSONALAI_CLASSROOM_ACCOUNTS` and `PERSONALAI_DRIVE_ACCOUNTS`. With both a calendar and a Classroom account, upcoming deadlines appear as pending approvals.
3. Set `PERSONALAI_FILE_ROOTS` to the folders the agent may read, for example `C:\Users\you\Documents\College;C:\Users\you\Notes`. The index (txt, md, csv, pdf, docx) is built at startup and refreshed every `PERSONALAI_FILE_INDEX_MINUTES` minutes.

### Evaluating the classifier

`uv run python -m agent.mail.evaluate` runs the rules-only classifier over `tests/fixtures/mail_labelled.json` (synthetic mail; undecided mail counts as normal) and prints per-class precision, recall and F1 plus a confusion matrix. Add `--ollama` to include the local model, and `--fixtures PATH` to use your own labelled file (same format: `vip_senders`, `college_domains` and an `items` list).
