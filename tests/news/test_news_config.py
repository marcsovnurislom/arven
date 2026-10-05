import copy

import pytest
import yaml
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR
from arven.core.news_config import NEWS_FILE, NewsConfig, load_news_config


def raw():
    return yaml.safe_load((DEFAULT_CONFIG_DIR / NEWS_FILE).read_text(encoding="utf-8"))


def test_repo_config_loads_and_hash_is_stable():
    cfg = load_news_config()
    assert cfg.feeds and cfg.max_items_per_tick >= 1
    assert cfg.config_hash() == load_news_config().config_hash()


def test_config_hash_changes_with_a_value():
    doc = raw()
    doc["max_items_per_tick"] = 1
    assert NewsConfig.model_validate(doc).config_hash() != load_news_config().config_hash()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(max_items_per_tick=0),
        lambda d: d.update(max_items_per_tick=500),
        lambda d: d.update(max_tokens=0),
        lambda d: d.update(unknown_field=1),
        lambda d: d.pop("feeds"),
    ],
)
def test_invalid_config_rejected(mutate):
    doc = copy.deepcopy(raw())
    mutate(doc)
    with pytest.raises(ValidationError):
        NewsConfig.model_validate(doc)
