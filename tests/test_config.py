from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from btc5m.config import Config, load_config

CONFIG_PATH = Path(__file__).parents[1] / "config" / "btc5m.toml"


def test_complete_configuration_loads_exact_decimal_and_stable_hash():
    config = load_config(CONFIG_PATH)
    assert config.risk.trade_budget_usd == Decimal("5")
    assert config.risk.trade_budget_usd / Decimal("10") == Decimal(".5")
    assert config.fingerprint == load_config(CONFIG_PATH).fingerprint
    with pytest.raises(FrozenInstanceError):
        config.strategy.mode = "momentum"  # type: ignore[misc]


@pytest.mark.parametrize("extra", ["surprise = true\n", "\n[unknown]\nvalue = 1\n"])
def test_unknown_configuration_rejected(tmp_path, extra):
    path = tmp_path / "bad.toml"
    path.write_text(extra + CONFIG_PATH.read_text())
    with pytest.raises(ValueError, match="unknown"):
        load_config(path)


def test_missing_section_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('[strategy]\nmode = "value"\n')
    with pytest.raises(ValueError, match="missing"):
        load_config(path)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "true", '"NaN"', "0", "-1"])
def test_invalid_budget_rejected_from_toml(tmp_path, value):
    path = tmp_path / "bad.toml"
    path.write_text(
        CONFIG_PATH.read_text().replace("trade_budget_usd = 5", f"trade_budget_usd = {value}")
    )
    with pytest.raises(ValueError):
        load_config(path)


@pytest.mark.parametrize(
    "updates",
    [
        {"mode": "secret"},
        {"entry_min_seconds": 59},
        {"entry_max_seconds": 301},
        {"entry_min_seconds": 181},
        {"momentum_min_seconds": 59},
        {"momentum_max_seconds": 181},
        {"volatility_short_seconds": 1801},
        {"volatility_stress_multiplier": Decimal("NaN")},
        {"value_min_ask": Decimal(".93")},
        {"max_spread": Decimal("-1")},
    ],
)
def test_invalid_strategy_settings_rejected(updates):
    with pytest.raises(ValueError):
        replace(Config().strategy, **updates)


def test_configuration_hash_changes_with_material_setting():
    config = Config()
    changed = replace(config, strategy=replace(config.strategy, mode="momentum"))
    assert config.fingerprint != changed.fingerprint


def test_budget_cannot_exceed_wallet_or_loss_allocation():
    config = Config()
    with pytest.raises(ValueError):
        replace(config.risk, trade_budget_usd=Decimal("101"))


def test_sampling_configuration_rejects_forward_fill_and_incompatible_windows():
    config = Config()
    with pytest.raises(ValueError):
        replace(config.data, sample_tolerance_ms=5000)
    with pytest.raises(ValueError):
        replace(config, strategy=replace(config.strategy, volatility_short_seconds=301))
