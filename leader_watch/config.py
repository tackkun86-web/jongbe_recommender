"""Environment-driven configuration for the 09:00-10:30 leader-watch system."""
from __future__ import annotations

import datetime
import os
from dataclasses import dataclass


def _parse_time(value: str) -> datetime.time:
    hour, minute = value.strip().split(":")
    return datetime.time(int(hour), int(minute))


@dataclass(frozen=True)
class Config:
    early_candidate_time: datetime.time
    early_candidate_end_time: datetime.time
    confirmation_time: datetime.time
    monitoring_end_time: datetime.time

    early_min_score: int
    confirmation_min_score: int

    early_trading_value_rank: int
    confirmation_trading_value_rank: int

    max_gap_percent: float
    max_confirmation_drawdown_percent: float
    max_weakness_drawdown_percent: float

    min_theme_followers: int
    alert_cooldown_seconds: int
    poll_interval_seconds: int
    market_timezone: str

    # Not in the original spec list but required for robust implementation.
    stale_threshold_seconds: int
    score_renotify_delta: int
    db_path: str


_DEFAULTS = {
    "EARLY_CANDIDATE_TIME": "09:05",
    "EARLY_CANDIDATE_END_TIME": "09:10",
    "CONFIRMATION_TIME": "09:30",
    "MONITORING_END_TIME": "10:30",
    "EARLY_MIN_SCORE": "70",
    "CONFIRMATION_MIN_SCORE": "75",
    "EARLY_TRADING_VALUE_RANK": "50",
    "CONFIRMATION_TRADING_VALUE_RANK": "30",
    "MAX_GAP_PERCENT": "8",
    "MAX_CONFIRMATION_DRAWDOWN_PERCENT": "3",
    "MAX_WEAKNESS_DRAWDOWN_PERCENT": "5",
    "MIN_THEME_FOLLOWERS": "2",
    "ALERT_COOLDOWN_SECONDS": "300",
    "POLL_INTERVAL_SECONDS": "2",
    "MARKET_TIMEZONE": "Asia/Seoul",
    "STALE_THRESHOLD_SECONDS": "30",
    "SCORE_RENOTIFY_DELTA": "10",
    "LEADER_WATCH_DB_PATH": os.path.join("leader_watch", "data", "alerts.db"),
}


def load_config(env: dict | None = None) -> Config:
    source = os.environ if env is None else env
    get = lambda key: source.get(key, _DEFAULTS[key])  # noqa: E731

    return Config(
        early_candidate_time=_parse_time(get("EARLY_CANDIDATE_TIME")),
        early_candidate_end_time=_parse_time(get("EARLY_CANDIDATE_END_TIME")),
        confirmation_time=_parse_time(get("CONFIRMATION_TIME")),
        monitoring_end_time=_parse_time(get("MONITORING_END_TIME")),
        early_min_score=int(get("EARLY_MIN_SCORE")),
        confirmation_min_score=int(get("CONFIRMATION_MIN_SCORE")),
        early_trading_value_rank=int(get("EARLY_TRADING_VALUE_RANK")),
        confirmation_trading_value_rank=int(get("CONFIRMATION_TRADING_VALUE_RANK")),
        max_gap_percent=float(get("MAX_GAP_PERCENT")),
        max_confirmation_drawdown_percent=float(get("MAX_CONFIRMATION_DRAWDOWN_PERCENT")),
        max_weakness_drawdown_percent=float(get("MAX_WEAKNESS_DRAWDOWN_PERCENT")),
        min_theme_followers=int(get("MIN_THEME_FOLLOWERS")),
        alert_cooldown_seconds=int(get("ALERT_COOLDOWN_SECONDS")),
        poll_interval_seconds=int(get("POLL_INTERVAL_SECONDS")),
        market_timezone=get("MARKET_TIMEZONE"),
        stale_threshold_seconds=int(get("STALE_THRESHOLD_SECONDS")),
        score_renotify_delta=int(get("SCORE_RENOTIFY_DELTA")),
        db_path=get("LEADER_WATCH_DB_PATH"),
    )
