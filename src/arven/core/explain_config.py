"""Stage 10 explanation/Q&A configuration (``config/explain.yaml``). Own hash, same pattern as
``news.yaml``/``ml.yaml``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from arven.core.config import DEFAULT_CONFIG_DIR, _read_yaml, _StrictModel

EXPLAIN_FILE = "explain.yaml"


class ExplainConfig(_StrictModel):
    llm_model: str
    max_tokens_explain: int = Field(ge=1, le=4096)
    max_tokens_qa: int = Field(ge=1, le=4096)
    n_decisions_context: int = Field(ge=0, le=500)
    n_news_context: int = Field(ge=0, le=500)

    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_explain_config(config_dir: Path | str | None = None) -> ExplainConfig:
    config_dir = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    return ExplainConfig.model_validate(_read_yaml(config_dir / EXPLAIN_FILE))
