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

Secrets are never read from the environment; they live in the OS keyring.
