"""Instrument overlays (config/instruments) and session closures: the default BTC configuration must keep the exact
hash it had before multi-instrument support (every stored run records it), and the gold overlays must load."""

import shutil

import pytest
from pydantic import ValidationError

from arven.core.config import DEFAULT_CONFIG_DIR, instrument_names, load_config
from arven.core.time import to_ms

# AppConfig.config_hash() of the repository's default configuration, recorded on 2026-10-18 before calendars and
# instrument overlays were added. A change here means every earlier run manifest no longer matches.
BTC_CONFIG_HASH = "3d75098a48aa86faefec9324e50743dd93b1b377af6aaee1385fd17b061058ed"


def test_default_btc_config_hash_unchanged():
    cfg = load_config()
    assert cfg.config_hash() == BTC_CONFIG_HASH
    assert cfg.instrument is None and cfg.dukascopy is None
    assert cfg.market.session == "24x7" and cfg.session_calendar().always_open


def test_repository_instruments_load():
    assert {"XAUUSD", "XAUUSDT"} <= set(instrument_names())
    duka = load_config(instrument="XAUUSD")
    assert (duka.market.symbol, duka.market.exchange, duka.market.market_type) == ("XAUUSD", "dukascopy", "spot_otc")
    assert duka.market.session == "cme_metals" and duka.dukascopy is not None and duka.dukascopy.point == 1000
    perp = load_config(instrument="XAUUSDT")
    assert (perp.market.symbol, perp.market.exchange) == ("XAUUSDT", "binance")
    assert perp.market.session == "cme_metals" and perp.dukascopy is None
    # everything not in the overlay is shared with the default config
    base = load_config()
    for cfg in (duka, perp):
        assert cfg.data == base.data and cfg.splits == base.splits
        assert cfg.market.feature_timeframes == base.market.feature_timeframes
    assert len({base.config_hash(), duka.config_hash(), perp.config_hash()}) == 3


def _copy_config(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(DEFAULT_CONFIG_DIR, d)
    return d


def test_closures_csv_is_loaded_and_changes_the_hash(tmp_path):
    d = _copy_config(tmp_path)
    before = load_config(d, instrument="XAUUSD")
    csv = d / "sessions" / "cme_metals_closures.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "2024-03-28T21:00:00Z,2024-03-31T22:00:00Z,Good Friday,test\n",
                   encoding="utf-8")
    after = load_config(d, instrument="XAUUSD")
    assert len(after.market.session_closures) == len(before.market.session_closures) + 1
    assert after.config_hash() != before.config_hash()
    cal = after.session_calendar()
    assert cal.is_open(to_ms(after.market.session_closures[-1].start)) is False
    assert load_config(d).config_hash() == BTC_CONFIG_HASH  # BTC never reads the CSV


def test_dukascopy_transport_settings_do_not_change_the_hash(tmp_path):
    d = _copy_config(tmp_path)
    before = load_config(d, instrument="XAUUSD").config_hash()
    p = d / "instruments" / "XAUUSD.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("workers: 4", "workers: 2"), encoding="utf-8")
    assert load_config(d, instrument="XAUUSD").config_hash() == before
    p.write_text(p.read_text(encoding="utf-8").replace("point: 1000", "point: 100"), encoding="utf-8")
    assert load_config(d, instrument="XAUUSD").config_hash() != before


def test_unknown_overlay_key_rejected(tmp_path):
    d = _copy_config(tmp_path)
    (d / "instruments" / "BAD.yaml").write_text("market:\n  symbol: BAD\nsplits: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown overlay keys"):
        load_config(d, instrument="BAD")


def test_dukascopy_exchange_requires_its_section(tmp_path):
    d = _copy_config(tmp_path)
    (d / "instruments" / "NOSRC.yaml").write_text(
        "market:\n  exchange: dukascopy\n  market_type: spot_otc\n  symbol: NOSRC\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="dukascopy section"):
        load_config(d, instrument="NOSRC")


def test_exchange_and_market_type_must_match(tmp_path):
    d = _copy_config(tmp_path)
    (d / "instruments" / "MIX.yaml").write_text(
        "market:\n  exchange: binance\n  market_type: spot_otc\n  symbol: MIX\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="spot_otc"):
        load_config(d, instrument="MIX")


def test_closure_bounds_must_be_whole_minutes(tmp_path):
    d = _copy_config(tmp_path)
    csv = d / "sessions" / "cme_metals_closures.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "2024-03-28T21:00:30Z,2024-03-31T22:00:00Z,bad,test\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="whole minutes"):
        load_config(d, instrument="XAUUSD")


def test_cli_refuses_instrument_for_commands_not_yet_instrument_aware():
    from arven.cli import main

    with pytest.raises(SystemExit, match="does not support --instrument"):
        main(["--instrument", "XAUUSD", "features", "status"])
    with pytest.raises(SystemExit, match="Binance bulk files"):
        main(["--instrument", "XAUUSD", "ingest", "--start", "2024-01-01", "--end", "2024-01-02"])
    with pytest.raises(SystemExit, match="Dukascopy instrument"):
        main(["--instrument", "XAUUSDT", "duka", "download", "--start", "2024-01-01", "--end", "2024-01-02"])
