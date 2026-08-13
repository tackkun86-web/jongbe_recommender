import pytest
from leader_watch.providers.kis.config import KisConfig, KisConfigError, load_kis_config


def test_missing_app_key_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_SECRET": "secret"})


def test_missing_app_secret_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key"})


def test_defaults_when_only_credentials_given():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret"})
    assert cfg.app_key == "key"
    assert cfg.app_secret == "secret"
    assert cfg.env == "real"
    assert cfg.universe_size == 100
    assert cfg.ranking_refresh_seconds == 20
    assert cfg.max_requests_per_second == 15


def test_env_overrides_are_applied():
    cfg = load_kis_config(env={
        "KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret",
        "KIS_ENV": "paper", "KIS_UNIVERSE_SIZE": "50",
        "KIS_RANKING_REFRESH_SECONDS": "10", "KIS_MAX_REQUESTS_PER_SECOND": "5",
    })
    assert cfg.env == "paper"
    assert cfg.universe_size == 50
    assert cfg.ranking_refresh_seconds == 10
    assert cfg.max_requests_per_second == 5


def test_invalid_env_value_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "bogus"})


def test_base_url_for_real_env():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "real"})
    assert cfg.base_url == "https://openapi.koreainvestment.com:9443"


def test_base_url_for_paper_env():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "paper"})
    assert cfg.base_url == "https://openapivts.koreainvestment.com:29443"


def test_non_numeric_universe_size_raises_kis_config_error_not_bare_value_error():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_UNIVERSE_SIZE": "abc"})


def test_non_numeric_ranking_refresh_seconds_raises_kis_config_error_not_bare_value_error():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_RANKING_REFRESH_SECONDS": "abc"})


def test_non_numeric_max_requests_per_second_raises_kis_config_error_not_bare_value_error():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_MAX_REQUESTS_PER_SECOND": "abc"})


def test_zero_max_requests_per_second_raises_kis_config_error_not_zero_division_error():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_MAX_REQUESTS_PER_SECOND": "0"})


def test_negative_universe_size_raises_kis_config_error():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_UNIVERSE_SIZE": "-5"})
