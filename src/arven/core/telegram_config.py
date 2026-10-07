"""Phase 6 Telegram configuration (``config/telegram.yaml``) plus the chat-id allow-list, which is a
secret (``TELEGRAM_CHAT_IDS``, comma-separated, in the environment/``.env`` - never in a YAML file
committed to the repo, same reasoning as ``ANTHROPIC_API_KEY``)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pydantic import Field

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

TELEGRAM_FILE = "telegram.yaml"


class TelegramConfig(_StrictModel):
    dry_run: bool
    command_poll_timeout_seconds: int = Field(ge=0, le=50)  # Telegram's own getUpdates timeout cap
    max_send_attempts: int = Field(ge=1, le=20)

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_telegram_config(config_dir: Path | str | None = None) -> TelegramConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return TelegramConfig.model_validate(_read_yaml(config_dir / TELEGRAM_FILE))


def _load_dotenv_once() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def allowed_chat_ids() -> frozenset[str]:
    """``TELEGRAM_CHAT_IDS`` as a comma-separated allow-list - empty (never implicitly "allow everyone")
    if unset, so a misconfigured deployment fails closed, not open."""
    raw = os.environ.get("TELEGRAM_CHAT_IDS")
    if not raw:
        _load_dotenv_once()
        raw = os.environ.get("TELEGRAM_CHAT_IDS")
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())
