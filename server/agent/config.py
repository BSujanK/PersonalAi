"""Runtime settings. Secrets are never read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    bind_hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 8765
    db_path: Path = Path.home() / ".personalai" / "agent.db"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5:3b"
    owner_emails: tuple[str, ...] = ()
    pairing_window_seconds: int = 300
    max_agent_steps: int = 6

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        defaults = cls()
        return cls(
            bind_hosts=_split(e["PERSONALAI_BIND_HOSTS"])
            if "PERSONALAI_BIND_HOSTS" in e
            else defaults.bind_hosts,
            port=int(e.get("PERSONALAI_PORT", defaults.port)),
            db_path=Path(e["PERSONALAI_DB_PATH"])
            if "PERSONALAI_DB_PATH" in e
            else defaults.db_path,
            nvidia_model=e.get("PERSONALAI_NVIDIA_MODEL", defaults.nvidia_model),
            owner_emails=_split(e.get("PERSONALAI_OWNER_EMAILS", "")),
        )
