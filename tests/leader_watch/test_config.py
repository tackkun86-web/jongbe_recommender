import datetime
from leader_watch.config import load_config


def test_defaults_when_env_empty():
    cfg = load_config(env={})
    assert cfg.early_candidate_time == datetime.time(9, 5)
    assert cfg.early_candidate_end_time == datetime.time(9, 10)
    assert cfg.confirmation_time == datetime.time(9, 30)
    assert cfg.monitoring_end_time == datetime.time(10, 30)
    assert cfg.early_min_score == 70
    assert cfg.confirmation_min_score == 75
    assert cfg.early_trading_value_rank == 50
    assert cfg.confirmation_trading_value_rank == 30
    assert cfg.max_gap_percent == 8.0
    assert cfg.max_confirmation_drawdown_percent == 3.0
    assert cfg.max_weakness_drawdown_percent == 5.0
    assert cfg.min_theme_followers == 2
    assert cfg.alert_cooldown_seconds == 300
    assert cfg.poll_interval_seconds == 2
    assert cfg.market_timezone == "Asia/Seoul"
    assert cfg.stale_threshold_seconds == 30
    assert cfg.score_renotify_delta == 10


def test_env_overrides_are_applied():
    cfg = load_config(env={"EARLY_MIN_SCORE": "80", "MAX_GAP_PERCENT": "5.5"})
    assert cfg.early_min_score == 80
    assert cfg.max_gap_percent == 5.5
