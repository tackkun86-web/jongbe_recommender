"""Data model for the 09:00-10:30 leader-watch system."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


def safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not denominator:
        return default
    return numerator / denominator


class Phase(str, Enum):
    INIT_COLLECT = "init_collect"
    EARLY_CANDIDATE = "early_candidate"
    VALIDATION = "validation"
    CONFIRMATION = "confirmation"
    MONITORING = "monitoring"
    POST_MONITORING = "post_monitoring"


class CandidateStatus(str, Enum):
    ACTIVE = "active"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    WEAKENED = "weakened"
    RECOVERED = "recovered"


@dataclass
class MinuteBar:
    timestamp: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def is_bearish_long_candle(self, avg_volume: float, body_pct_threshold: float = 2.0) -> bool:
        body_pct = safe_ratio(self.open - self.close, self.open) * 100
        return self.close < self.open and body_pct >= body_pct_threshold and self.volume > avg_volume


@dataclass
class StockSnapshot:
    code: str
    name: str
    market: str
    timestamp: datetime.datetime
    current_price: float
    prev_close: float
    open_price: float
    high_price: float
    low_price: float
    cum_volume: int
    cum_trading_value: float
    market_trading_value_rank: int
    execution_strength: float
    theme: Optional[str]
    theme_trading_value_rank: Optional[int]
    news_today: bool
    news_continuing: bool
    minute_bars_1m: list[MinuteBar] = field(default_factory=list)
    minute_bars_5m: list[MinuteBar] = field(default_factory=list)
    avg_trading_value_same_time_20d: Optional[float] = None
    avg_volume_same_time_20d: Optional[float] = None
    is_trading_halted: bool = False
    is_administrative: bool = False
    is_investment_alert: bool = False
    is_etf_etn: bool = False
    is_preferred_share: bool = False

    @property
    def change_pct(self) -> float:
        return safe_ratio(self.current_price - self.prev_close, self.prev_close) * 100

    @property
    def vs_open_pct(self) -> float:
        return safe_ratio(self.current_price - self.open_price, self.open_price) * 100

    @property
    def gap_from_prev_close_pct(self) -> float:
        return safe_ratio(self.open_price - self.prev_close, self.prev_close) * 100


@dataclass
class ScoreBreakdown:
    trading_value: float
    theme_leadership: float
    price_strength: float
    minute_flow: float
    news: float
    missing_categories: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return (
            self.trading_value
            + self.theme_leadership
            + self.price_strength
            + self.minute_flow
            + self.news
        )

    @property
    def confidence(self) -> str:
        return "low" if self.missing_categories else "high"


@dataclass
class CandidateState:
    code: str
    name: str
    phase: Phase
    status: CandidateStatus
    score: float
    market_rank: Optional[int] = None
    theme_rank: Optional[int] = None
    high_since_confirm: Optional[float] = None
    first_30min_low: Optional[float] = None
    consecutive_open_recovery_fail: int = 0
    early_candidate_streak: int = 0
    leader_change_streak: int = 0
    snapshot_history: list[StockSnapshot] = field(default_factory=list)
    last_alert_sent: dict[str, tuple[datetime.datetime, float]] = field(default_factory=dict)
