import pytest
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError, load_kiwoom_config


def test_missing_bridge_token_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={})


def test_defaults_when_only_token_given():
    cfg = load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok"})
    assert cfg.bridge_token == "tok"
    assert cfg.bridge_url == "http://127.0.0.1:8000"
    assert cfg.universe_size == 100
    assert cfg.ranking_refresh_seconds == 20


def test_env_overrides_are_applied():
    cfg = load_kiwoom_config(env={
        "KIWOOM_BRIDGE_TOKEN": "tok",
        "KIWOOM_BRIDGE_URL": "http://127.0.0.1:9000",
        "KIWOOM_UNIVERSE_SIZE": "50",
        "KIWOOM_RANKING_REFRESH_SECONDS": "10",
    })
    assert cfg.bridge_url == "http://127.0.0.1:9000"
    assert cfg.universe_size == 50
    assert cfg.ranking_refresh_seconds == 10


def test_non_numeric_universe_size_raises_kiwoom_config_error_not_value_error():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_UNIVERSE_SIZE": "abc"})


def test_non_numeric_ranking_refresh_seconds_raises_kiwoom_config_error():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_RANKING_REFRESH_SECONDS": "abc"})


def test_zero_universe_size_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_UNIVERSE_SIZE": "0"})


def test_negative_ranking_refresh_seconds_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_RANKING_REFRESH_SECONDS": "-5"})
