import copy
from pathlib import Path

import pytest
import yaml

from arven.core.config import CONFIG_FILES, DEFAULT_CONFIG_DIR, AppConfig, load_config


def repo_config_docs() -> dict[str, dict]:
    return {
        name: yaml.safe_load((DEFAULT_CONFIG_DIR / name).read_text(encoding="utf-8")) for name in CONFIG_FILES
    }


def write_config(config_dir: Path, docs: dict[str, dict]) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    for name, content in docs.items():
        (config_dir / name).write_text(yaml.safe_dump(content), encoding="utf-8")
    return config_dir


@pytest.fixture
def make_config(tmp_path):
    """Build an AppConfig whose data_dir lives in tmp_path; ``overrides`` maps 'file.section.key' -> value."""

    def _make(**overrides) -> AppConfig:
        docs = copy.deepcopy(repo_config_docs())
        docs["default.yaml"]["data"]["data_dir"] = str(tmp_path / "data")
        docs["default.yaml"]["download"]["backoff_initial_seconds"] = 0.0
        for dotted, value in overrides.items():
            file_stem, *path = dotted.split("__")
            node = docs[f"{file_stem}.yaml"]
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
        return load_config(write_config(tmp_path / "config", docs))

    return _make
