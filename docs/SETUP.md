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

## Go-live guide (M7): Windows laptop and Android phone

The short path is three things you do by hand, then two commands. Run PowerShell as your normal user (not as admin).

### Before the wizard

1. **Laptop tools.** Install [Python 3.12+](https://www.python.org/downloads/windows/), [uv](https://docs.astral.sh/uv/getting-started/installation/) (`winget install --id=astral-sh.uv -e`), Git, [Ollama](https://ollama.com/download) and [Tailscale](https://tailscale.com/download/windows). Sign in to Tailscale and, in the admin console, choose **Disable key expiry** for the laptop. Clone the repo, for example to `C:\Users\you\PersonalAi`.
2. **Phone.** Install Tailscale from the Play Store, sign in with the same account and turn on **Always-on VPN** for it. Build and sideload the APK ([A8](#a8-build-and-install-the-android-app)), enrol a fingerprint, and set the app and Tailscale to **Battery: Unrestricted**.
3. **Accounts you create in a browser.** The wizard cannot do these for you:
   - a Google Cloud OAuth **Desktop** client, published **In production** ([A3](#a3-google-cloud-oauth-production-mode), items 1 to 5); keep the downloaded client JSON at hand;
   - an NVIDIA API key from [build.nvidia.com](https://build.nvidia.com/) (starts with `nvapi-`).

### Run the wizard

From `server\`:

```powershell
uv run python -m agent setup
```

It follows the appendix below in order and asks before every change. Each step checks whether it is already done and skips it, so you can stop at any point (Ctrl+C) and run it again to continue; `--redo STEP` repeats one step (`prereqs`, `nvidia_key`, `models`, `ollama`, `google`, `profile`, `network`, `task`, `power`, `pair`). The steps:

1. checks Python and uv, runs `uv sync`;
2. asks for the NVIDIA key with hidden input and stores it in Windows Credential Manager only;
3. lists the models your key can use, offers to run `scripts/eval_models.py` on the ones you pick, then sets `PERSONALAI_MODEL_PRIMARY`, `_FALLBACK` and `_LONG` from your choice ([A4a](#a4a-choose-the-nvidia-models) explains how to choose);
4. pulls the Ollama models and sets `OLLAMA_CONTEXT_LENGTH` and `PERSONALAI_LOCAL_CONTEXT_TOKENS` to the same value (quit Ollama from the tray and start it again afterwards);
5. signs in each Google account you enter, with the services you choose (a browser opens), and adds it to the `PERSONALAI_*_ACCOUNTS` variables; delete the client JSON afterwards;
6. asks for your addresses, VIP senders, college domains and readable folders;
7. finds the laptop's Tailscale `100.x.y.z` address and sets `PERSONALAI_BIND_HOSTS` to `127.0.0.1,100.x.y.z`;
8. installs and starts the "PersonalAi agent" scheduled task;
9. checks the power settings and shows the `powercfg` commands for you to run yourself (it never changes them);
10. opens a pairing window and shows the QR code to scan in the app (**Settings > Pair**);
11. finishes by running `agent doctor`.

Every value is written as a Windows **user** environment variable (no file in the repo), and every secret goes only to Credential Manager. Open a new PowerShell window afterwards so it sees the variables.

### Check everything

```powershell
uv run python -m agent doctor
```

It prints a pass/fail line per prerequisite, with the exact command that fixes each failure: Python and uv, the keyring backend, the NVIDIA key and that the configured models exist, Ollama and its context length, each Google account's granted services, the bind addresses and Tailscale, the database, its key and the audit chain, the scheduled task, power settings, a paired phone, and the last mail, SMS and Classroom sync times. It exits with 0 only when every required check passes (the sync times are informational). `--json` prints the same as JSON. It never prints keys, tokens, mail or SMS. Run it again whenever something seems off.

Then go through the first sync checks in [A12](#a12-first-sync-checks).

## Appendix: manual go-live steps

These are the steps the wizard automates, kept for reference and for fixing one thing by hand. Do them in order on the laptop and the phone. Each step ends with a check. Stop at the first check that fails.

### A1. Laptop prerequisites

1. Install [Python 3.12+](https://www.python.org/downloads/windows/), [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then clone the repo, for example to `C:\Users\you\PersonalAi`.
2. In `server\`, run `uv sync`.
3. Check the keyring backend is Windows Credential Manager:
   ```powershell
   uv run python -c "import keyring; print(keyring.get_keyring())"
   ```
   It must print `WinVaultKeyring` (possibly inside a `ChainerBackend`). The server refuses to start on any other backend; there is no plaintext fallback.

### A2. Tailscale

1. Install [Tailscale](https://tailscale.com/download/windows) on the laptop and sign in.
2. In the Tailscale admin console, open the laptop's machine menu and choose **Disable key expiry**, so the laptop does not drop off the tailnet after 180 days.
3. Note the laptop's address: `tailscale ip -4` (a `100.x.y.z` address; it stays the same for this machine).
4. Install Tailscale on the phone from the Play Store and sign in with the same account. In Android **Settings > Network > VPN > Tailscale**, turning on **Always-on VPN** keeps the phone connected.
5. Check: from the phone's browser, `http://100.x.y.z:8765` will answer later, once the server runs (step A7).

### A3. Google Cloud OAuth (production mode)

1. At [console.cloud.google.com](https://console.cloud.google.com/), create a project, for example `personalai`.
2. **APIs & Services > Library**: enable the Gmail API, Google Calendar API, Google Classroom API and Google Drive API.
3. **Google Auth Platform > Branding / Audience** (the OAuth consent screen): user type **External**, app name `PersonalAi`, your address as support and developer contact. Add each Google account you will sign in with as a test user while you set up.
4. **Audience > Publish app**, so the status is **In production**. This matters: in "Testing" mode refresh tokens expire after 7 days and the agent silently stops syncing. You do not need to submit for verification; Google shows a "Google hasn't verified this app" screen at sign-in, which you pass with **Advanced > Go to PersonalAi (unsafe)**. That is expected for a personal app used only by you.
5. **Clients > Create client**, type **Desktop app**. Download the client JSON.
6. From `server\`, authorise each account with the services you want it to use (scopes accumulate across runs, and `--client-secret` is only needed the first time):
   ```powershell
   uv run python scripts/setup_google_oauth.py --account you@example.com --services gmail,calendar,drive --client-secret C:\Users\you\Downloads\client_secret.json
   uv run python scripts/setup_google_oauth.py --account you@college.example.edu --services gmail,classroom,drive
   ```
   A browser opens on `127.0.0.1`; sign in as that account and allow everything asked. The client JSON and the tokens go only into the keyring.
7. Delete the downloaded client JSON.
8. If the college Workspace admin blocks third-party apps (the sign-in shows "access blocked" or "admin_policy_enforced"), set up forwarding from the college mailbox to your personal Gmail instead, and leave the college account out of every `PERSONALAI_*_ACCOUNTS` variable. Classroom is then unavailable.
9. Check: the script prints the account and the services it authorised, with no error.

### A4. NVIDIA API key

1. At [build.nvidia.com](https://build.nvidia.com/), sign in and generate an API key (it starts with `nvapi-`).
2. Store it in the keyring. The command prompts for the value without echoing it; never put the key on the command line, in a file or in an environment variable:
   ```powershell
   uv run python -m keyring set PersonalAi nvidia_api_key
   ```
3. Choose the models (next section), set `PERSONALAI_MODEL_PRIMARY`, then check: `uv run python scripts/check_nvidia.py` prints `OK: <model> reachable and tool calling works`. It sends one fixed synthetic prompt, nothing personal. `--model ID` checks another model without changing the variable.

### A4a. Choose the NVIDIA models

No model is built in: the server will not chat until `PERSONALAI_MODEL_PRIMARY` is set. The catalogue changes often, so pick from what your key can use today.

1. List the models your key can call (`GET /v1/models`; the key is read from the keyring, never typed):
   ```powershell
   uv run python scripts/eval_models.py --list-models
   ```
   Pick three to five instruct models that the model card says support tool (function) calling, plus one with a long context window.
2. Run the evaluation on them (from `server\`):
   ```powershell
   uv run python scripts/eval_models.py vendor/model-a vendor/model-b vendor/model-c
   ```
   It runs about 40 synthetic scenarios per model through the real agent loop, tools and redaction over fake accounts: tool choice and arguments, multi-step tasks, refusing instructions planted inside mail, files, Classroom and SMS, copying masked placeholders such as `⟨PHONE_1⟩` exactly, and plain answers. Only synthetic data is sent, and nothing reaches your real accounts. The table shows, per model, the pass rate (overall and per category), p50 and p95 latency per model call, the number of 429 (rate limit) responses and errors, followed by the IDs of failed scenarios.
   - The trial tier allows about 40 requests a minute, and each model makes roughly 80 to 120 calls. Add `--rpm 30` to pace the calls if the 429 column is high, and evaluate a few models per run. `--only injection,placeholder` or `--limit 10` give a quick pass; `--json results.json` saves the numbers.
3. Set the variables from the results:
   - `PERSONALAI_MODEL_PRIMARY`: the model with the best pass rate that has **no injection failures** and acceptable p95 latency. Injection and placeholder failures matter more than a slightly lower overall score.
   - `PERSONALAI_MODEL_FALLBACK`: the runner-up, ideally from a different vendor so one outage or rate limit does not take out both. Optional.
   - `PERSONALAI_MODEL_LONG`: a model with a large context window that also passed the injection scenarios, used when a request is longer than `PERSONALAI_LONG_CONTEXT_TOKENS`. Optional; without it long requests go to the primary.
   - `PERSONALAI_LONG_CONTEXT_TOKENS`: a bit below the primary model's context window, for example `24000` for a 32k model (the default is `32000`). The size is estimated as characters divided by four.
   ```powershell
   [Environment]::SetEnvironmentVariable("PERSONALAI_MODEL_PRIMARY", "vendor/model-a", "User")
   [Environment]::SetEnvironmentVariable("PERSONALAI_MODEL_FALLBACK", "vendor/model-b", "User")
   [Environment]::SetEnvironmentVariable("PERSONALAI_MODEL_LONG", "vendor/model-c", "User")
   [Environment]::SetEnvironmentVariable("PERSONALAI_LONG_CONTEXT_TOKENS", "24000", "User")
   ```
4. Re-run the evaluation when NVIDIA retires a model or adds a new one, and after changing the system prompt or tools.

**How requests are routed.** A long request goes to the long model, everything else to the primary. If that model errors or is rate limited, the request moves to the fallback model and then to local Ollama, but only when the request fits in `PERSONALAI_LOCAL_CONTEXT_TOKENS`. Chat replies stream to the app as they are generated; if a model fails mid-reply, the app clears the partial text and the next route answers. Every route receives only redacted text. The server log records which route and model answered each request (never its content), for example `llm served route=fallback model=vendor/model-b`.

### A5. Ollama (local classifier and fallback)

1. Install [Ollama for Windows](https://ollama.com/download) and let it run at startup (the default).
2. `ollama pull qwen2.5:3b`
3. Do not set `OLLAMA_HOST`; Ollama must stay on `127.0.0.1:11434`. The server refuses a non-loopback Ollama address.
4. Give Ollama a context window that fits the agent's prompts, and tell the server the same number. Prompts estimated larger than `PERSONALAI_LOCAL_CONTEXT_TOKENS` are never sent to Ollama (they fail with "llm unavailable" instead of being silently cut, which would drop the system prompt):
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "8192", "User")
   [Environment]::SetEnvironmentVariable("PERSONALAI_LOCAL_CONTEXT_TOKENS", "8192", "User")
   ```
   Quit Ollama from the tray icon and start it again so it reads the value.
5. Check: `ollama run qwen2.5:3b "say ok"` answers.

### A6. Configuration

Set your user environment variables once (they hold no secrets). Replace the examples with your values; see [Configuration](#configuration) for every variable.

```powershell
$vars = @{
  PERSONALAI_BIND_HOSTS        = "127.0.0.1,100.x.y.z"   # loopback plus the laptop's Tailscale IP
  PERSONALAI_MODEL_PRIMARY     = "vendor/model-a"        # from step A4a
  PERSONALAI_OWNER_EMAILS      = "you@example.com,you@college.example.edu"
  PERSONALAI_MAIL_ACCOUNTS     = "you@example.com,you@college.example.edu"
  PERSONALAI_CALENDAR_ACCOUNTS = "you@example.com"
  PERSONALAI_CLASSROOM_ACCOUNTS= "you@college.example.edu"
  PERSONALAI_DRIVE_ACCOUNTS    = "you@example.com,you@college.example.edu"
  PERSONALAI_COLLEGE_DOMAINS   = "college.example.edu"
  PERSONALAI_FILE_ROOTS        = "C:\Users\you\Documents\College;C:\Users\you\Notes"
}
foreach ($k in $vars.Keys) { [Environment]::SetEnvironmentVariable($k, $vars[$k], "User") }
```

Open a new PowerShell window afterwards so it sees the variables. The server refuses `0.0.0.0`, `::`, LAN addresses such as `192.168.x.x`, and anything else outside loopback and Tailscale.

### A7. First run (in a terminal)

1. From `server\`: `uv run python -m agent serve`. It prints nothing on success and keeps running. If it prints `refused: ...`, fix what it names.
2. Windows Firewall may ask about Python. If the phone cannot reach the server later, add an inbound rule that only allows the tailnet (run PowerShell as admin once):
   ```powershell
   New-NetFirewallRule -DisplayName "PersonalAi (Tailscale only)" -Direction Inbound -Protocol TCP -LocalPort 8765 -RemoteAddress 100.64.0.0/10 -Action Allow
   ```
   Never allow it for all addresses.
3. Check: `curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/today` prints `401` (the route exists and needs a device token).
4. Stop it with Ctrl+C once the phone is paired and step A11 passes; step A9 makes it start on its own.

### A8. Build and install the Android app

The CI `android` job builds a standalone **release** APK on every PR and push to `main` (artifact `personalai-apk`). It bundles the app's JavaScript, so it runs without a dev server. It is signed with Expo's template debug keystore, so each new build installs over the last one as an update. To get it: GitHub > **Actions** > the latest green run on `main` > **Artifacts** > `personalai-apk` (sign in to GitHub first). Chrome may flag the zip as dangerous because it contains an APK; choose **Download dangerous file**. Unzip it to get the `.apk`.

Later, to sign with your own key instead of the shared template key, build it one of these ways:

- **EAS (no Android SDK needed):** from `mobile\`, `npm ci`, then `npx eas-cli login` and `npx eas-cli build -p android --profile preview`. EAS creates and keeps the signing key for you. Download the APK from the link it prints. For push, see [Optional push](#optional-push) before building.
- **Local Gradle:** install Android Studio (it brings the SDK) and JDK 17. From `mobile\`: `npm ci`, `npx expo prebuild --platform android`, then in `mobile\android` run `.\gradlew assembleRelease`. Create your own release keystore first (`keytool -genkeypair -v -keystore personalai.jks -keyalg RSA -keysize 2048 -validity 10000 -alias personalai`), keep it outside the repo, and configure it in `android\app\build.gradle` `signingConfigs.release`. The APK is in `android\app\build\outputs\apk\release\`.
elease\`.

Switching signing keys means uninstalling the old app first, which also means pairing again.

Sideload it: copy the APK to the phone and open it (allow **Install unknown apps** for the Files app when asked), or `adb install path\to\app.apk` with USB debugging on.

On the phone:

1. Enrol a fingerprint or face unlock (**Settings > Security**) if you have not. Pairing fails without one; there is no fallback.
2. **Settings > Apps > PersonalAi > Battery**: set **Unrestricted**, so SMS upload and background sync are not killed. Do the same for Tailscale.

### A9. Start the server at logon (Task Scheduler)

1. From `server\`: `powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1`. It registers the task "PersonalAi agent" for your user: it starts one minute after logon (so Tailscale has its address), restarts every minute if the server exits, keeps running on battery, and runs hidden. It needs no admin rights and stores no secrets.
2. `Start-ScheduledTask -TaskName "PersonalAi agent"`, then repeat the check from step A7.3.
3. Check after a reboot: log in, wait two minutes, repeat step A7.3. The task runs only while you are logged in, because the keys are in your user's Credential Manager.

### A10. Power settings

The server only answers while the laptop is awake.

1. **Settings > System > Power & battery > Screen, sleep & hibernate timeouts**: when plugged in, set **Make my device sleep after** to **Never**. Or, in PowerShell: `powercfg /change standby-timeout-ac 0` and `powercfg /change hibernate-timeout-ac 0`.
2. **Control Panel > Power Options > Choose what closing the lid does**: **When I close the lid, plugged in: Do nothing**. Or: `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0`, then `powercfg /setactive SCHEME_CURRENT`.
3. **Device Manager > Network adapters > your Wi-Fi adapter > Properties > Power Management**: untick **Allow the computer to turn off this device to save power**.
4. On battery, keep Windows defaults; the phone simply queues SMS and retries until the laptop is back.

### A11. Pair the phone

1. With the server running, from `server\`: `uv run python -m agent pair`. It prints a QR code and a one-time code valid for 5 minutes.
2. In the app: **Settings > Pair**, scan the QR (or type `http://100.x.y.z:8765` and the code). The app refuses any address outside the tailnet.
3. Confirm with your fingerprint when asked. The approval key is stored behind that unlock.
4. Check: the Today screen loads.
5. If you paired before (a test phone, an older install), list devices with `uv run python -m agent devices` and revoke the old ones with `uv run python -m agent revoke --device ID`.

### A12. First sync checks

Go through these once; they are the end-to-end acceptance list from `docs/PLAN.md`.

- [ ] `scripts/check_nvidia.py` passed (step A4).
- [ ] Mail: within `PERSONALAI_MAIL_POLL_MINUTES` of starting, the digest in the app covers the last 7 days, and the important/normal split looks right.
- [ ] Calendar and Classroom: upcoming Classroom deadlines appear as pending approvals; approving one creates the event.
- [ ] Ask "Remind me at 7am": an approval appears on the phone, the fingerprint prompt follows, and the alarm is set in the clock app (open the app after approving).
- [ ] Ask "Draft a reply to <someone>": the exact text is shown; reject it; check Gmail Sent that nothing was sent.
- [ ] Bank SMS: **Settings > Import bank SMS**, allow SMS; a real Bank of Baroda SMS appears in Money, and the balance matches the latest "Avl Bal".
- [ ] Turn Tailscale off on the phone: the app can no longer reach the server. Turn it back on.
- [ ] Take the first backup (below) and store the passphrase in your password manager.

## Backup and restore

The database holds your mail index, ledger and history (sensitive columns are encrypted with `db_key`, which lives in the keyring). A backup is one encrypted file that holds the database and `db_key`, so it can be restored on a new laptop.

```powershell
uv run python -m agent backup --out D:\backups\personalai-2026-10-05.paibak
uv run python -m agent restore --in D:\backups\personalai-2026-10-05.paibak          # stop the server first
```

- The passphrase is prompted for (twice for a backup), at least 12 characters, and never taken from the command line or environment. Without it the backup cannot be opened, so keep it in a password manager, not on the laptop.
- Format: AES-256-GCM with a key derived from the passphrase by scrypt; the header is authenticated too, so any change to the file makes it fail to open. A backup never overwrites an existing file.
- The backup does **not** hold the phone pairing, approval keys, Google tokens or the NVIDIA key. After restoring on a new laptop, redo steps A3 (sign-in only), A4 and A11 (or `agent setup --redo google --redo nvidia_key --redo pair`).
- `restore` refuses to replace an existing database, or a different `db_key` in the keyring, unless you add `--force`. With `--force` the old database is renamed to `agent.db.pre-restore-<timestamp>` and the old key is kept in the keyring as `db_key.pre-restore-<timestamp>`; nothing is deleted.
- Stop the scheduled task before restoring (`Stop-ScheduledTask -TaskName "PersonalAi agent"`) and start it again afterwards.
- Suggested habit: a backup each week to an external drive or a cloud folder; the file is safe to store there because it is encrypted.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `PERSONALAI_BIND_HOSTS` | Comma-separated bind IPs (loopback or Tailscale only) | `127.0.0.1` |
| `PERSONALAI_PORT` | Port | `8765` |
| `PERSONALAI_DB_PATH` | SQLite file | `~/.personalai/agent.db` |
| `PERSONALAI_MODEL_PRIMARY` | NVIDIA Build model for normal requests (required for chat; see step A4a) | none |
| `PERSONALAI_MODEL_FALLBACK` | Model used when the primary (or long) model errors or is rate limited | none |
| `PERSONALAI_MODEL_LONG` | Model for requests longer than `PERSONALAI_LONG_CONTEXT_TOKENS` | none (primary) |
| `PERSONALAI_LONG_CONTEXT_TOKENS` | Estimated size (characters / 4) above which the long model is used | `32000` |
| `PERSONALAI_LOCAL_CONTEXT_TOKENS` | Ollama's context window; larger prompts skip the local fallback instead of being truncated. Set `OLLAMA_CONTEXT_LENGTH` to the same value | `8192` |
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
| `PERSONALAI_FINANCE_UTC_OFFSET_MINUTES` | Local time offset for finance periods (India is +330) | `330` |
| `PERSONALAI_FINANCE_CATEGORIZE_MINUTES` | How often uncategorised transactions go to the local model | `15` |

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

## Finance (M4, finish with the phone app in M5 and on the laptop in M7)

1. Nothing to configure on the laptop beyond the variables above. The phone app reads bank SMS (Bank of Baroda `BOBTXN`/`BOBSMS`, HDFC, SBI, ICICI, Axis, Kotak, Canara and UPI apps), queues them while the laptop is offline, and sends them in batches to `POST /sms`. Re-sending a batch is safe: duplicates are skipped.
2. With mail configured, bank alert emails in the synced accounts are read too and merged with the matching SMS, so a payment is counted once.
3. Uncategorised transactions are sent to the local Ollama model (the same `PERSONALAI_CLASSIFIER_MODEL` as mail). Corrections from the app can be remembered per payee.
4. Balances are the latest "Avl Bal" figure from each account's bank messages, keyed by the masked account number. They are never estimated.

### Evaluating the classifier

`uv run python -m agent.mail.evaluate` runs the rules-only classifier over `tests/fixtures/mail_labelled.json` (synthetic mail; undecided mail counts as normal) and prints per-class precision, recall and F1 plus a confusion matrix. Add `--ollama` to include the local model, and `--fixtures PATH` to use your own labelled file (same format: `vip_senders`, `college_domains` and an `items` list).

## Mobile app (M5)

The Android app lives in `mobile/` (Expo SDK 57, TypeScript). It is a dev-client/prebuild app, not Expo Go, because it reads SMS and stores keys in the Android Keystore. `mobile/android` is generated and gitignored.

### Build and install

1. Prerequisites: Node 22, and either the Android SDK with JDK 17 (local build) or an Expo account (EAS build).
2. From `mobile/` run `npm ci`.
3. Get an APK, either way:
   - Local: `npx expo prebuild --platform android`, then `npx expo run:android` with the phone connected over USB (debugging on).
   - EAS: `npx eas-cli build -p android --profile preview`, then download the APK. The `development` profile builds a dev client instead.
4. Sideload with `adb install path/to/app.apk`, or open the EAS download link on the phone.

### Pair the phone

1. On the laptop, bind the server to its Tailscale IP (`PERSONALAI_BIND_HOSTS` accepts only loopback or Tailscale addresses) and run `python -m agent pair`. It opens a short pairing window and prints a QR code.
2. Install Tailscale on the phone and join the same tailnet.
3. Open the app and scan the QR code (or type the `http://100.x.y.z:8765` URL and code by hand). The app accepts only `http://` Tailscale IP addresses (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`); MagicDNS names are refused.
4. Pairing needs a fingerprint or face unlock enrolled on the phone. The approval key is stored behind that unlock, so approving an action always prompts for it. If no biometric is enrolled, pairing fails; there is no fallback.
5. Settings, then Unpair, wipes the token and key from the phone. Revoke the device on the laptop as well: `uv run python -m agent devices` lists them, `uv run python -m agent revoke --device ID` (or `--all`) revokes.

### Permissions

- SMS (read and receive): Settings, then "Import bank SMS" asks the first time. Only messages from the bank sender list (plus any sender starting with `BOB`) are stored and sent. Add your own sender IDs in Settings. Queued messages upload when the app opens, after an import and about every 15 minutes in the background.
- Notifications: asked when you turn on push, and needed for reminders.
- Camera: only for scanning the pairing QR.
- Alarms and timers set by the agent are created through the Android clock app after you approve them. They run while the app is open (Android blocks launching the clock from the background), so open the app after approving.

### Optional push

Polling every 30 seconds while the app is open works with no setup. For push notifications ("1 approval pending", never any content):

1. Create a Firebase project, add an Android app with package `com.bsujank.personalai`, and download `google-services.json`. Keep it out of git (it is gitignored). Pass its path as the `GOOGLE_SERVICES_JSON` environment variable for local builds, or as an EAS file secret of the same name.
2. Run `npx eas-cli init` in `mobile/` and set the project id as `EAS_PROJECT_ID` (it feeds `extra.eas.projectId`) for local and EAS builds.
3. Set `PERSONALAI_PUSH=expo` on the laptop and restart the server.
4. Rebuild the APK, then turn on "Push notifications" in Settings. Without a project id the toggle is disabled and the app keeps polling.

### Checks

`cd mobile && npm ci && npx tsc --noEmit && npx eslint . && npx jest --ci`. The Kotlin SMS module (`mobile/modules/bank-sms`) is compiled by the CI `android` job (Expo prebuild plus Gradle `assembleRelease`); its runtime behaviour (SMS receiver, alarms, push) still has to be checked on the phone.
