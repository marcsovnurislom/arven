import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.explain_config import EXPLAIN_FILE, ExplainConfig, load_explain_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / EXPLAIN_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_explain_config()
    assert cfg.llm_model and cfg.max_tokens_explain >= 1 and cfg.max_tokens_qa >= 1
    assert cfg.config_hash() == load_explain_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["max_tokens_explain"] = 1
    assert ExplainConfig.model_validate(doc).config_hash() != load_explain_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(max_tokens_explain=0),
        lambda d: d.update(max_tokens_qa=0),
        lambda d: d.update(n_decisions_context=-1),
        lambda d: d.update(n_news_context=-1),
        lambda d: d.update(unknown_field=1),
        lambda d: d.pop("llm_model"),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        ExplainConfig.model_validate(doc)
