"""Stage 9b news/LLM configuration (``config/news.yaml``). Own hash, same pattern as ``ml.yaml``/
``features.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

NEWS_FILE = "news.yaml"


class NewsConfig(_StrictModel):
    feeds: dict[str, str]  # source name -> RSS URL
    llm_model: str
    max_items_per_tick: int = Field(ge=1, le=200)  # cost control: a hard cap on LLM calls per `arven news run`
    max_tokens: int = Field(ge=1, le=4096)

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_news_config(config_dir: Path | str | None = None) -> NewsConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return NewsConfig.model_validate(_read_yaml(config_dir / NEWS_FILE))
