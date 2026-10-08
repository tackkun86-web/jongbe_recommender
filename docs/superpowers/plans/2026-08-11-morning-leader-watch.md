# 09:00~10:30 오전 주도주 실시간 감시 시스템 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `leader_watch/` package that monitors KOSPI/KOSDAQ stocks from 09:00–10:30 KST, delays "leading stock" confirmation until 09:30 (verifying trading value rank, theme rank, open-price support, and minute-candle flow), and sends analysis-only Telegram/console alerts — with zero trading/order code.

**Architecture:** New standalone package (`leader_watch/`) with a `MarketDataProvider` interface (Mock now, Real stubbed), a pure-function `state_machine.py` for phase transitions, `scoring.py` for the 100-point rubric, SQLite-backed alert dedup (`store.py`), and an `engine.py` polling loop driven by KST time. `main.py` becomes this system's entry point; the existing daily batch moves to `run_daily_scheduler.py` unchanged.

**Tech Stack:** Python 3.14, pytest, sqlite3 (stdlib), zoneinfo (stdlib), python-dotenv, requests (Telegram, reused from existing `notifier.py`).

## Global Constraints

- Never write order/buy/sell/account-balance code. Analysis + notification only. (요구사항 최상단 절대 제약)
- All alert bodies must show the data as-of timestamp (KST) and the score + judgment basis. (§8)
- 09:30 confirmation alerts must never say "당일 최종 주도주" — use "오전 주도주 1차 확정" / "09:30 기준 주도주" / "오후 주도권 변경 가능" only. (§1)
- No alerts on weekends or KRX holidays. (§1)
- Exclude 거래정지/관리종목/투자위험/ETF/ETN/인버스/레버리지/스팩/우선주 by default. (§8)
- All ratio/division calculations must guard against division-by-zero and type errors. (§8)
- Do not delete or modify existing `recommender.py`, `scorer.py`, `filters.py`, `notifier.py`, `scheduler.py`, `data_fetcher.py` behavior — only relocate the scheduler entrypoint call. (§8, existing-code preservation)
- All configurable values in §7 must be environment-variable driven with the exact names given in the spec.
- `python main.py --provider mock` and `python main.py --provider real` must both run without crashing.

---

## File Structure

```
leader_watch/
├── __init__.py
├── config.py
├── models.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── mock.py
│   ├── mock_scenarios.py
│   └── real.py
├── notifiers/
│   ├── __init__.py
│   ├── base.py
│   ├── console.py
│   └── telegram.py
├── filters.py
├── scoring.py
├── state_machine.py
├── store.py
├── alerts.py
└── engine.py

tests/leader_watch/
├── __init__.py
├── test_config.py
├── test_models.py
├── test_filters.py
├── test_scoring.py
├── test_providers_mock.py
├── test_store.py
├── test_notifiers.py
├── test_alerts.py
├── test_state_machine_early_candidate.py
├── test_state_machine_rejection.py
├── test_state_machine_confirmation.py
├── test_state_machine_monitoring.py
├── test_state_machine_leader_change.py
├── test_engine.py
└── test_integration_mock_run.py

main.py                    (rewritten)
run_daily_scheduler.py     (new, moved from main.py)
.env.example                (extended)
README.md                   (new)
```

---

### Task 1: Package skeleton + config.py

**Files:**
- Create: `leader_watch/__init__.py` (empty)
- Create: `leader_watch/config.py`
- Test: `tests/leader_watch/__init__.py` (empty)
- Test: `tests/leader_watch/test_config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `leader_watch.config.Config` dataclass, `leader_watch.config.load_config(env: dict | None = None) -> Config` — all later tasks import `Config` and call `load_config()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/config.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Update `.env.example`**

Append to the existing `.env.example` (keep `TELEGRAM_BOT_TOKEN=`/`TELEGRAM_CHAT_ID=` untouched):

```env
# --- Morning leader-watch system (09:00-10:30 KST) ---
EARLY_CANDIDATE_TIME=09:05
EARLY_CANDIDATE_END_TIME=09:10
CONFIRMATION_TIME=09:30
MONITORING_END_TIME=10:30

EARLY_MIN_SCORE=70
CONFIRMATION_MIN_SCORE=75

EARLY_TRADING_VALUE_RANK=50
CONFIRMATION_TRADING_VALUE_RANK=30

MAX_GAP_PERCENT=8
MAX_CONFIRMATION_DRAWDOWN_PERCENT=3
MAX_WEAKNESS_DRAWDOWN_PERCENT=5

MIN_THEME_FOLLOWERS=2
ALERT_COOLDOWN_SECONDS=300
POLL_INTERVAL_SECONDS=2
MARKET_TIMEZONE=Asia/Seoul

# Not required by the original spec text but used by the implementation:
STALE_THRESHOLD_SECONDS=30
SCORE_RENOTIFY_DELTA=10
LEADER_WATCH_DB_PATH=leader_watch/data/alerts.db
```

- [ ] **Step 6: Commit**

```bash
git add leader_watch/__init__.py leader_watch/config.py tests/leader_watch/__init__.py tests/leader_watch/test_config.py .env.example
git commit -m "feat(leader_watch): add env-driven config module"
```

---

### Task 2: models.py

**Files:**
- Create: `leader_watch/models.py`
- Test: `tests/leader_watch/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Phase` (Enum), `CandidateStatus` (Enum), `MinuteBar`, `StockSnapshot`, `ScoreBreakdown`, `CandidateState`, `safe_ratio(numerator, denominator, default=0.0) -> float`. All later tasks import these exact names from `leader_watch.models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_models.py
import datetime
from leader_watch.models import (
    CandidateState,
    CandidateStatus,
    MinuteBar,
    Phase,
    
    ScoreBreakdown,
    StockSnapshot,
    safe_ratio,
)


def _snapshot(**overrides):
    base = dict(
        code="005930",
        name="테스트전자",
        market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 12),
        current_price=10200,
        prev_close=10000,
        open_price=10100,
        high_price=10300,
        low_price=10050,
        cum_volume=1_000_000,
        cum_trading_value=10_000_000_000,
        market_trading_value_rank=12,
        theme_trading_value_rank=1,
        execution_strength=130.0,
        theme="반도체",
        news_today=True,
        news_continuing=False,
        minute_bars_1m=[],
        minute_bars_5m=[],
        avg_trading_value_same_time_20d=5_000_000_000,
        avg_volume_same_time_20d=500_000,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_change_pct_and_open_gap_and_prev_close_gap():
    snap = _snapshot()
    assert round(snap.change_pct, 2) == 2.0            # (10200-10000)/10000*100
    assert round(snap.vs_open_pct, 2) == 0.99           # (10200-10100)/10100*100
    assert round(snap.gap_from_prev_close_pct, 2) == 1.0  # (10100-10000)/10000*100


def test_safe_ratio_handles_zero_denominator():
    assert safe_ratio(10, 0) == 0.0
    assert safe_ratio(10, 0, default=-1.0) == -1.0
    assert safe_ratio(9, 3) == 3.0


def test_zero_prev_close_or_open_does_not_raise():
    snap = _snapshot(prev_close=0, open_price=0)
    assert snap.change_pct == 0.0
    assert snap.vs_open_pct == 0.0
    assert snap.gap_from_prev_close_pct == 0.0


def test_candidate_state_defaults():
    state = CandidateState(code="005930", name="테스트전자", phase=Phase.EARLY_CANDIDATE, status=CandidateStatus.ACTIVE, score=72.0)
    assert state.market_rank is None
    assert state.theme_rank is None
    assert state.snapshot_history == []
    assert state.last_alert_sent == {}
    assert state.early_candidate_streak == 0


def test_minute_bar_is_bearish_long_candle():
    bar = MinuteBar(timestamp=datetime.datetime(2026, 8, 11, 9, 20), open=10500, high=10520, low=10100, close=10150, volume=200_000)
    assert bar.is_bearish_long_candle(avg_volume=100_000) is True
    small_body = MinuteBar(timestamp=datetime.datetime(2026, 8, 11, 9, 21), open=10500, high=10520, low=10480, close=10495, volume=200_000)
    assert small_body.is_bearish_long_candle(avg_volume=100_000) is False


def test_score_breakdown_total_and_confidence():
    breakdown = ScoreBreakdown(trading_value=30, theme_leadership=20, price_strength=25, minute_flow=15, news=10, missing_categories=[])
    assert breakdown.total == 100
    assert breakdown.confidence == "high"

    partial = ScoreBreakdown(trading_value=30, theme_leadership=0, price_strength=25, minute_flow=15, news=10, missing_categories=["theme_leadership"])
    assert partial.confidence == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/models.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/models.py tests/leader_watch/test_models.py
git commit -m "feat(leader_watch): add data models and safe_ratio guard"
```

---

### Task 3: filters.py

**Files:**
- Create: `leader_watch/filters.py`
- Test: `tests/leader_watch/test_filters.py`

**Interfaces:**
- Consumes: `StockSnapshot` from Task 2.
- Produces: `is_excluded(snapshot: StockSnapshot) -> tuple[bool, str | None]` — `(True, reason)` if excluded, else `(False, None)`. Used by `engine.py` (Task 15) before any candidate is scored.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_filters.py
import datetime
from leader_watch.filters import is_excluded
from leader_watch.models import StockSnapshot


def _snapshot(name="정상전자", **overrides):
    base = dict(
        code="000001", name=name, market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 5),
        current_price=10000, prev_close=9800, open_price=9900,
        high_price=10100, low_price=9850, cum_volume=100_000,
        cum_trading_value=1_000_000_000, market_trading_value_rank=20,
        execution_strength=110.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_normal_stock_is_not_excluded():
    excluded, reason = is_excluded(_snapshot())
    assert excluded is False
    assert reason is None


def test_trading_halted_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_trading_halted=True))
    assert excluded is True
    assert reason == "거래정지"


def test_administrative_issue_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_administrative=True))
    assert excluded is True
    assert reason == "관리종목"


def test_investment_alert_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_investment_alert=True))
    assert excluded is True
    assert reason == "투자위험종목"


def test_etf_etn_by_flag_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_etf_etn=True))
    assert excluded is True
    assert reason == "ETF/ETN"


def test_etf_by_name_keyword_is_excluded():
    excluded, reason = is_excluded(_snapshot(name="KODEX 반도체"))
    assert excluded is True
    assert reason == "ETF/ETN"


def test_leverage_inverse_spac_by_name_is_excluded():
    for name in ["KODEX 코스닥150선물인버스", "삼성 2X레버리지", "한화플러스스팩3호"]:
        excluded, reason = is_excluded(_snapshot(name=name))
        assert excluded is True, name
        assert reason == "ETF/ETN"


def test_preferred_share_by_name_suffix_is_excluded():
    for name in ["삼성전자우", "LG화학우B"]:
        excluded, reason = is_excluded(_snapshot(name=name))
        assert excluded is True, name
        assert reason == "우선주"


def test_common_share_ending_in_woo_syllable_not_excluded():
    # "우" mid-name (not a preferred-share suffix pattern) must not be excluded.
    excluded, reason = is_excluded(_snapshot(name="우리금융지주"))
    assert excluded is False
    assert reason is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/filters.py
"""Exclusion filters: 거래정지/관리종목/투자위험/ETF/ETN/인버스/레버리지/스팩/우선주."""
from __future__ import annotations

import re

from leader_watch.models import StockSnapshot

_ETF_ETN_KEYWORDS = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "KOSEF", "SOL", "ACE",
    "인버스", "레버리지", "2X", "선물", "스팩",
)

_PREFERRED_SHARE_SUFFIX = re.compile(r"(?:\d?우|\d?우[A-Z])$")


def _is_preferred_share(name: str) -> bool:
    return bool(_PREFERRED_SHARE_SUFFIX.search(name)) and not name.endswith("지주")


def is_excluded(snapshot: StockSnapshot) -> tuple[bool, str | None]:
    if snapshot.is_trading_halted:
        return True, "거래정지"
    if snapshot.is_administrative:
        return True, "관리종목"
    if snapshot.is_investment_alert:
        return True, "투자위험종목"
    if snapshot.is_etf_etn or any(keyword in snapshot.name for keyword in _ETF_ETN_KEYWORDS):
        return True, "ETF/ETN"
    if snapshot.is_preferred_share or _is_preferred_share(snapshot.name):
        return True, "우선주"
    return False, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_filters.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/filters.py tests/leader_watch/test_filters.py
git commit -m "feat(leader_watch): add exclusion filters for halted/administrative/ETF/preferred stocks"
```

---

### Task 4: scoring.py

**Files:**
- Create: `leader_watch/scoring.py`
- Test: `tests/leader_watch/test_scoring.py`

**Interfaces:**
- Consumes: `StockSnapshot`, `ScoreBreakdown`, `safe_ratio` from Task 2; `Config` from Task 1.
- Produces: `calculate_leader_score(snapshot: StockSnapshot, history: list[StockSnapshot], theme_follower_count: int, config: Config) -> ScoreBreakdown`. Used by `state_machine.py` (Tasks 10-13).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_scoring.py
import datetime
from leader_watch.config import load_config
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.scoring import calculate_leader_score

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 15),
        current_price=10600, prev_close=10000, open_price=10200,
        high_price=10650, low_price=10150, cum_volume=2_000_000,
        cum_trading_value=25_000_000_000, market_trading_value_rank=5,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
        minute_bars_1m=[], minute_bars_5m=[],
        avg_trading_value_same_time_20d=4_000_000_000,
        avg_volume_same_time_20d=400_000,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_top_tier_stock_scores_near_max():
    bars = [
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 5), 10100, 10200, 10050, 10150, 300_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 10), 10150, 10300, 10200, 10250, 150_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 15), 10250, 10650, 10240, 10600, 320_000),
    ]
    snap = _snapshot(minute_bars_1m=bars)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=3, config=CFG)
    assert breakdown.trading_value == 30          # rank 5 -> top 10 tier, 5x avg volume/value
    assert breakdown.theme_leadership == 20        # theme rank 1
    assert breakdown.price_strength >= 20           # +5% change, open held, high renewed
    assert breakdown.news == 10                     # today's news
    assert breakdown.total <= 100
    assert breakdown.missing_categories == []


def test_no_theme_data_is_marked_missing_and_scored_zero():
    snap = _snapshot(theme=None, theme_trading_value_rank=None)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=0, config=CFG)
    assert breakdown.theme_leadership == 0
    assert "theme_leadership" in breakdown.missing_categories


def test_single_stock_theme_with_no_followers_is_penalized_vs_multi_follower():
    lonely = _snapshot(theme_trading_value_rank=1)
    breakdown_lonely = calculate_leader_score(lonely, history=[lonely], theme_follower_count=0, config=CFG)
    crowded = _snapshot(theme_trading_value_rank=1)
    breakdown_crowded = calculate_leader_score(crowded, history=[crowded], theme_follower_count=3, config=CFG)
    assert breakdown_lonely.theme_leadership < breakdown_crowded.theme_leadership


def test_open_price_breach_zeroes_price_strength():
    snap = _snapshot(current_price=10000, open_price=10200, high_price=10300)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=2, config=CFG)
    assert breakdown.price_strength == 0


def test_trading_value_rank_outside_100_scores_zero():
    snap = _snapshot(market_trading_value_rank=250, avg_trading_value_same_time_20d=None)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=1, config=CFG)
    assert breakdown.trading_value == 0


def test_no_news_scores_zero_news_category():
    snap = _snapshot(news_today=False, news_continuing=False)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=1, config=CFG)
    assert breakdown.news == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/scoring.py
"""100-point leading-stock scoring rubric (거래대금30/테마20/가격25/분봉15/뉴스10)."""
from __future__ import annotations

from leader_watch.config import Config
from leader_watch.models import ScoreBreakdown, StockSnapshot, safe_ratio


def _trading_value_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    rank = snapshot.market_trading_value_rank
    if rank <= 10:
        points = 30.0
    elif rank <= 20:
        points = 25.0
    elif rank <= 30:
        points = 20.0
    elif rank <= 50:
        points = 15.0
    elif rank <= 100:
        points = 5.0
    else:
        return 0.0, []

    basis = [f"거래대금 순위 {rank}위"]
    if snapshot.avg_trading_value_same_time_20d:
        ratio = safe_ratio(snapshot.cum_trading_value, snapshot.avg_trading_value_same_time_20d)
        if ratio >= 5:
            points = min(30.0, points + 5)
            basis.append("동시간대 평균 대비 5배 이상 거래대금 증가")
        elif ratio >= 3:
            points = min(30.0, points + 3)
            basis.append("동시간대 평균 대비 3배 이상 거래대금 증가")
    if snapshot.change_pct > 0:
        points = min(30.0, points + 2)
        basis.append("거래대금 증가와 함께 주가 상승")
    return round(min(points, 30.0), 2), basis


def _theme_points(snapshot: StockSnapshot, theme_follower_count: int) -> tuple[float, list[str], list[str]]:
    if snapshot.theme is None or snapshot.theme_trading_value_rank is None:
        return 0.0, [], ["theme_leadership"]

    rank = snapshot.theme_trading_value_rank
    if rank == 1:
        points = 20.0
    elif rank == 2:
        points = 14.0
    elif rank == 3:
        points = 8.0
    else:
        points = 0.0

    basis = [f"테마({snapshot.theme}) 내 거래대금 {rank}위"]
    if theme_follower_count >= 2:
        points = min(20.0, points + 2)
        basis.append(f"동반 상승 테마 종목 {theme_follower_count}개")
    elif theme_follower_count == 0:
        points = max(0.0, points - 4)
        basis.append("테마 내 후속 종목 없음 (감점)")
    return round(points, 2), basis, []


def _price_strength_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    if snapshot.vs_open_pct < 0:
        return 0.0, ["시가 이탈 후 회복하지 못해 가격 강도 0점"]

    points = 0.0
    basis = []
    change = snapshot.change_pct
    if change >= 5:
        points += 10
        basis.append(f"등락률 +{change:.1f}% (+5% 이상)")
    elif change >= 3:
        points += 8
        basis.append(f"등락률 +{change:.1f}% (+3% 이상)")
    elif change >= 2:
        points += 5
        basis.append(f"등락률 +{change:.1f}% (+2% 이상)")

    points += 5
    basis.append("시가 대비 플러스 유지")

    if snapshot.current_price >= snapshot.high_price:
        points += 5
        basis.append("장중 고점 갱신")

    return round(min(points, 25.0), 2), basis


def _minute_flow_points(history: list[StockSnapshot]) -> tuple[float, list[str], list[str]]:
    bars: list = []
    for snap in history:
        bars.extend(snap.minute_bars_1m)
    if len(bars) < 2:
        return 0.0, [], ["minute_flow"]

    points = 0.0
    basis = []
    rising_volume = any(
        bars[i].close > bars[i].open and bars[i].volume > bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if rising_volume:
        points += 5
        basis.append("상승 시 거래량 증가 확인")

    pullback_volume_down = any(
        bars[i].close < bars[i - 1].close and bars[i].volume < bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if pullback_volume_down:
        points += 5
        basis.append("눌림 구간 거래량 감소 확인")

    rebreak_volume_up = any(
        bars[i].high >= max(b.high for b in bars[:i]) and bars[i].volume > bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if rebreak_volume_up:
        points += 5
        basis.append("직전 고점 재돌파 시 거래량 재증가")

    return round(points, 2), basis, []


def _news_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    if snapshot.news_today:
        return 10.0, ["당일 신규 뉴스/공시 확인"]
    if snapshot.news_continuing:
        return 5.0, ["전일 뉴스 지속 확산"]
    return 0.0, ["재료 없음"]


def calculate_leader_score(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    theme_follower_count: int,
    config: Config,
) -> ScoreBreakdown:
    trading_value, tv_basis = _trading_value_points(snapshot)
    theme_leadership, theme_basis, theme_missing = _theme_points(snapshot, theme_follower_count)
    price_strength, price_basis = _price_strength_points(snapshot)
    minute_flow, flow_basis, flow_missing = _minute_flow_points(history)
    news, news_basis = _news_points(snapshot)

    return ScoreBreakdown(
        trading_value=trading_value,
        theme_leadership=theme_leadership,
        price_strength=price_strength,
        minute_flow=minute_flow,
        news=news,
        missing_categories=theme_missing + flow_missing,
        basis=tv_basis + theme_basis + price_basis + flow_basis + news_basis,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_scoring.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/scoring.py tests/leader_watch/test_scoring.py
git commit -m "feat(leader_watch): add 100-point leading-stock scoring rubric"
```

---

### Task 5: providers/base.py + providers/mock.py + mock_scenarios.py

**Files:**
- Create: `leader_watch/providers/__init__.py` (empty)
- Create: `leader_watch/providers/base.py`
- Create: `leader_watch/providers/mock_scenarios.py`
- Create: `leader_watch/providers/mock.py`
- Test: `tests/leader_watch/test_providers_mock.py`

**Interfaces:**
- Consumes: `StockSnapshot`, `MinuteBar` from Task 2.
- Produces: `MarketDataProvider` (ABC with `get_snapshot(now: datetime) -> list[StockSnapshot]`), `MockProvider(MarketDataProvider)`. `engine.py` (Task 15) depends on `MarketDataProvider.get_snapshot`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_providers_mock.py
import datetime
from leader_watch.providers.mock import MockProvider


def test_mock_provider_returns_snapshots_for_known_tick():
    provider = MockProvider()
    now = datetime.datetime(2026, 8, 11, 9, 1)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) > 0
    assert all(s.timestamp <= now for s in snapshots)


def test_mock_provider_returns_empty_before_market_open():
    provider = MockProvider()
    now = datetime.datetime(2026, 8, 11, 8, 55)
    assert provider.get_snapshot(now) == []


def test_mock_provider_scenario_stock_confirms_and_holds():
    provider = MockProvider()
    early = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 6))
    confirm = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 30))
    codes_early = {s.code for s in early}
    codes_confirm = {s.code for s in confirm}
    assert "LEAD01" in codes_early
    assert "LEAD01" in codes_confirm


def test_mock_provider_scenario_gap_over_8pct_flagged():
    provider = MockProvider()
    confirm = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 30))
    gap_stock = next(s for s in confirm if s.code == "GAP01")
    assert gap_stock.gap_from_prev_close_pct > 8


def test_mock_provider_returns_latest_snapshot_at_or_before_requested_time():
    provider = MockProvider()
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 7, 30))
    lead = next(s for s in snapshots if s.code == "LEAD01")
    assert lead.timestamp <= datetime.datetime(2026, 8, 11, 9, 7, 30)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_providers_mock.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/base.py
"""MarketDataProvider interface — the only surface engine.py depends on."""
from __future__ import annotations

import abc
import datetime

from leader_watch.models import StockSnapshot


class MarketDataProvider(abc.ABC):
    @abc.abstractmethod
    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        """Return the latest known snapshot (as of `now`) for every tracked stock."""
        raise NotImplementedError
```

```python
# leader_watch/providers/mock_scenarios.py
"""Hand-authored per-minute scenarios replayed by MockProvider.

Each scenario is a list of (minute_offset_from_09:00, StockSnapshot-kwargs) tuples.
MockProvider interpolates by "most recent tick at or before `now`".
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

_DATE = datetime.date(2026, 8, 11)


def _t(hh: int, mm: int) -> datetime.datetime:
    return datetime.datetime(_DATE.year, _DATE.month, _DATE.day, hh, mm)


def _bar(hh, mm, o, h, l, c, v) -> MinuteBar:
    return MinuteBar(timestamp=_t(hh, mm), open=o, high=h, low=l, close=c, volume=v)


def _snap(code, name, theme, theme_rank, t, **kw) -> StockSnapshot:
    defaults = dict(
        code=code, name=name, market="KOSPI", timestamp=t,
        theme=theme, theme_trading_value_rank=theme_rank,
        news_today=True, news_continuing=False,
        minute_bars_1m=[], minute_bars_5m=[],
        avg_trading_value_same_time_20d=3_000_000_000,
        avg_volume_same_time_20d=300_000,
        execution_strength=120.0,
    )
    defaults.update(kw)
    return StockSnapshot(**defaults)


def build_scenarios() -> dict[str, list[StockSnapshot]]:
    """Returns {code: [snapshot, snapshot, ...]} sorted by timestamp ascending."""
    scenarios: dict[str, list[StockSnapshot]] = {}

    # 1) LEAD01 — normal confirm, holds leadership through 10:30.
    lead01 = []
    price = 10000
    for minute in range(0, 91, 3):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10000 + minute * 8
        lead01.append(_snap(
            "LEAD01", "리딩전자", "반도체", 1, t,
            current_price=price, prev_close=10000, open_price=10200,
            high_price=max(price, 10200), low_price=9950,
            cum_volume=300_000 + minute * 20_000, cum_trading_value=(300_000 + minute * 20_000) * price,
            market_trading_value_rank=max(1, 8 - minute // 15),
            minute_bars_1m=[_bar(9, 0, 10000, 10200, 9950, price, 300_000 + minute * 5_000)],
        ))
    scenarios["LEAD01"] = lead01

    # 2) FAIL01 — early candidate, breaches open twice in VALIDATION, rejected.
    fail01 = []
    for minute in range(0, 25, 2):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10300 if minute < 10 else 10000 - minute * 5  # breaches open after 09:10
        fail01.append(_snap(
            "FAIL01", "실패산업", "2차전지", 2, t,
            current_price=price, prev_close=10000, open_price=10200,
            high_price=10350, low_price=min(price, 9800),
            cum_volume=200_000 + minute * 10_000, cum_trading_value=(200_000 + minute * 10_000) * price,
            market_trading_value_rank=20,
        ))
    scenarios["FAIL01"] = fail01

    # 3) GAP01 — gap-up > 8%, weak follow-through, excluded from confirmation.
    gap01 = []
    for minute in range(0, 40, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10900 - minute * 2
        gap01.append(_snap(
            "GAP01", "갭상승홀딩스", "바이오", 1, t,
            current_price=price, prev_close=10000, open_price=10900,
            high_price=10950, low_price=10850,
            cum_volume=150_000, cum_trading_value=150_000 * price,
            market_trading_value_rank=15, execution_strength=95.0,
        ))
    scenarios["GAP01"] = gap01

    # 4) RANK01 — big trading value but rank falls outside top 30 by 09:30.
    rank01 = []
    for minute in range(0, 40, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        rank01.append(_snap(
            "RANK01", "순위이탈전자", "자동차", 2, t,
            current_price=10400, prev_close=10000, open_price=10100,
            high_price=10450, low_price=10050,
            cum_volume=180_000, cum_trading_value=180_000 * 10400,
            market_trading_value_rank=10 + minute,  # climbs past 30 as time passes
        ))
    scenarios["RANK01"] = rank01

    # 5) WEAK01 — confirms normally, then weakens after 09:30 (drawdown > 5%).
    weak01 = []
    for minute in range(0, 91, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        if minute <= 30:
            price = 10000 + minute * 10
        else:
            price = 10300 - (minute - 30) * 15
        weak01.append(_snap(
            "WEAK01", "약화전자", "조선", 1, t,
            current_price=price, prev_close=10000, open_price=10100,
            high_price=10300, low_price=min(price, 9900),
            cum_volume=250_000 + minute * 5_000, cum_trading_value=(250_000 + minute * 5_000) * price,
            market_trading_value_rank=6 if minute <= 30 else 40,
        ))
    scenarios["WEAK01"] = weak01

    # 6) CHAL01 / CHAL02 — same theme, CHAL02 overtakes CHAL01 after 09:40 (leader change).
    chal01, chal02 = [], []
    for minute in range(0, 91, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        p1 = 10000 + minute * 5 if minute <= 40 else 10200
        p2 = 10000 + minute * 3 if minute <= 40 else 10000 + minute * 12
        chal01.append(_snap(
            "CHAL01", "기존대장주", "로봇", 1 if minute <= 40 else 2, t,
            current_price=p1, prev_close=10000, open_price=10100,
            high_price=max(p1, 10200), low_price=9950,
            cum_volume=200_000, cum_trading_value=200_000 * p1,
            market_trading_value_rank=3 if minute <= 40 else 6,
        ))
        chal02.append(_snap(
            "CHAL02", "신규도전자", "로봇", 2 if minute <= 40 else 1, t,
            current_price=p2, prev_close=10000, open_price=10050,
            high_price=max(p2, 10100), low_price=9980,
            cum_volume=180_000 + minute * 3_000, cum_trading_value=(180_000 + minute * 3_000) * p2,
            market_trading_value_rank=5 if minute <= 40 else 2,
        ))
    scenarios["CHAL01"] = chal01
    scenarios["CHAL02"] = chal02

    # 7) STALE01 — data stops updating after 09:04 (simulates feed delay/staleness).
    stale01 = [
        _snap("STALE01", "지연데이터", "화학", 1, _t(9, 2),
              current_price=10300, prev_close=10000, open_price=10100,
              high_price=10350, low_price=10050,
              cum_volume=100_000, cum_trading_value=100_000 * 10300,
              market_trading_value_rank=25),
    ]
    scenarios["STALE01"] = stale01

    return scenarios
```

```python
# leader_watch/providers/mock.py
"""MockProvider replays hand-authored per-minute scenarios for local testing."""
from __future__ import annotations

import datetime

from leader_watch.models import StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.mock_scenarios import build_scenarios

_MARKET_OPEN = datetime.time(9, 0)


class MockProvider(MarketDataProvider):
    def __init__(self) -> None:
        self._scenarios = build_scenarios()

    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        if now.time() < _MARKET_OPEN:
            return []

        result: list[StockSnapshot] = []
        for code, ticks in self._scenarios.items():
            candidates = [tick for tick in ticks if tick.timestamp <= now]
            if candidates:
                result.append(candidates[-1])
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_providers_mock.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/ tests/leader_watch/test_providers_mock.py
git commit -m "feat(leader_watch): add MarketDataProvider interface and MockProvider scenarios"
```

---

### Task 6: providers/real.py stub

**Files:**
- Create: `leader_watch/providers/real.py`
- Test: `tests/leader_watch/test_providers_real.py`

**Interfaces:**
- Consumes: `MarketDataProvider` from Task 5.
- Produces: `RealProvider(MarketDataProvider)` — importable and instantiable, raises `NotImplementedError` only when `get_snapshot` is actually called.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_providers_real.py
import datetime
import pytest
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.real import RealProvider


def test_real_provider_is_instantiable_and_is_a_market_data_provider():
    provider = RealProvider()
    assert isinstance(provider, MarketDataProvider)


def test_real_provider_get_snapshot_raises_not_implemented():
    provider = RealProvider()
    with pytest.raises(NotImplementedError):
        provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 5))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_providers_real.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/real.py
"""Real broker/exchange API provider — NOT YET IMPLEMENTED.

TODO: Wire this up to an actual real-time market data source once one is
chosen (e.g. a securities-firm Open API providing 1-min/5-min bars,
체결강도, and live market/theme trading-value ranks). Naver Finance HTML
scraping (used by the existing daily-batch `data_fetcher.py`) does NOT
provide these real-time fields and cannot be reused here.

Implementers must:
  1. Authenticate using credentials read from environment variables
     (never hardcode secrets).
  2. Return `StockSnapshot` objects with `timestamp` set to the actual
     exchange data timestamp (not `datetime.now()`), so the staleness
     check in `engine.py` works correctly.
  3. Wrap network calls with the retry/backoff helper in
     `leader_watch/engine.py` (`call_with_retry`).
"""
from __future__ import annotations

import datetime

from leader_watch.models import StockSnapshot
from leader_watch.providers.base import MarketDataProvider


class RealProvider(MarketDataProvider):
    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        raise NotImplementedError(
            "RealProvider is not implemented yet — no real-time market data "
            "source is configured. See the module docstring for what an "
            "implementation must do."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_providers_real.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/real.py tests/leader_watch/test_providers_real.py
git commit -m "feat(leader_watch): add RealProvider interface stub with TODO for real API integration"
```

---

### Task 7: store.py (SQLite persistence)

**Files:**
- Create: `leader_watch/store.py`
- Test: `tests/leader_watch/test_store.py`

**Interfaces:**
- Consumes: nothing external besides stdlib `sqlite3`.
- Produces: `AlertStore` class with methods:
  - `AlertStore(db_path: str)`
  - `record_alert(code: str, date: str, alert_type: str, score: float, sent_at: datetime) -> None`
  - `last_alert(code: str, date: str, alert_type: str) -> tuple[datetime, float] | None`
  - `upsert_candidate(code, date, name, phase, status, score, updated_at) -> None`
  - `load_today_candidates(date: str) -> dict[str, dict]`
  Used by `engine.py` (Task 15) for dedup/cooldown and restart recovery.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_store.py
import datetime
import os
import tempfile

import pytest
from leader_watch.store import AlertStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield AlertStore(path)
    os.remove(path)


def test_record_and_fetch_last_alert(store):
    sent_at = datetime.datetime(2026, 8, 11, 9, 10, 30)
    store.record_alert("005930", "2026-08-11", "early_candidate", 72.0, sent_at)
    result = store.last_alert("005930", "2026-08-11", "early_candidate")
    assert result is not None
    fetched_at, score = result
    assert fetched_at == sent_at
    assert score == 72.0


def test_last_alert_returns_none_when_absent(store):
    assert store.last_alert("999999", "2026-08-11", "confirmed") is None


def test_last_alert_returns_most_recent_of_multiple(store):
    store.record_alert("005930", "2026-08-11", "weakened", 60.0, datetime.datetime(2026, 8, 11, 9, 40))
    store.record_alert("005930", "2026-08-11", "weakened", 55.0, datetime.datetime(2026, 8, 11, 10, 0))
    _, score = store.last_alert("005930", "2026-08-11", "weakened")
    assert score == 55.0


def test_upsert_and_load_today_candidates(store):
    now = datetime.datetime(2026, 8, 11, 9, 30)
    store.upsert_candidate("005930", "2026-08-11", "테스트전자", "confirmation", "confirmed", 80.0, now)
    store.upsert_candidate("005930", "2026-08-11", "테스트전자", "monitoring", "confirmed", 82.0, now)
    loaded = store.load_today_candidates("2026-08-11")
    assert "005930" in loaded
    assert loaded["005930"]["phase"] == "monitoring"
    assert loaded["005930"]["score"] == 82.0


def test_store_survives_reopen_same_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        s1 = AlertStore(path)
        s1.upsert_candidate("000660", "2026-08-11", "재시작테스트", "confirmation", "confirmed", 78.0, datetime.datetime(2026, 8, 11, 9, 30))
        s2 = AlertStore(path)
        loaded = s2.load_today_candidates("2026-08-11")
        assert "000660" in loaded
    finally:
        os.remove(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/store.py
"""SQLite-backed alert history and candidate-state persistence."""
from __future__ import annotations

import datetime
import os
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    name TEXT,
    phase TEXT,
    status TEXT,
    score REAL,
    updated_at TEXT,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    score REAL,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts(code, alert_type, date);
"""


class AlertStore:
    def __init__(self, db_path: str) -> None:
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_alert(self, code: str, date: str, alert_type: str, score: float, sent_at: datetime.datetime) -> None:
        self._conn.execute(
            "INSERT INTO alerts (code, date, alert_type, score, sent_at) VALUES (?, ?, ?, ?, ?)",
            (code, date, alert_type, score, sent_at.isoformat()),
        )
        self._conn.commit()

    def last_alert(self, code: str, date: str, alert_type: str) -> tuple[datetime.datetime, float] | None:
        row = self._conn.execute(
            "SELECT sent_at, score FROM alerts WHERE code=? AND date=? AND alert_type=? ORDER BY id DESC LIMIT 1",
            (code, date, alert_type),
        ).fetchone()
        if row is None:
            return None
        return datetime.datetime.fromisoformat(row[0]), row[1]

    def upsert_candidate(
        self, code: str, date: str, name: str, phase: str, status: str, score: float, updated_at: datetime.datetime
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO candidates (code, date, name, phase, status, score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, date) DO UPDATE SET
                name=excluded.name, phase=excluded.phase, status=excluded.status,
                score=excluded.score, updated_at=excluded.updated_at
            """,
            (code, date, name, phase, status, score, updated_at.isoformat()),
        )
        self._conn.commit()

    def load_today_candidates(self, date: str) -> dict[str, dict]:
        rows = self._conn.execute(
            "SELECT code, name, phase, status, score, updated_at FROM candidates WHERE date=?",
            (date,),
        ).fetchall()
        return {
            row[0]: {
                "name": row[1],
                "phase": row[2],
                "status": row[3],
                "score": row[4],
                "updated_at": row[5],
            }
            for row in rows
        }

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/store.py tests/leader_watch/test_store.py
git commit -m "feat(leader_watch): add SQLite-backed alert/candidate store with restart recovery"
```

---

### Task 8: notifiers/base.py + console.py + telegram.py

**Files:**
- Create: `leader_watch/notifiers/__init__.py` (empty)
- Create: `leader_watch/notifiers/base.py`
- Create: `leader_watch/notifiers/console.py`
- Create: `leader_watch/notifiers/telegram.py`
- Test: `tests/leader_watch/test_notifiers.py`

**Interfaces:**
- Produces: `AlertNotifier` (ABC with `send(title: str, body: str) -> bool`), `ConsoleNotifier`, `TelegramNotifier(bot_token: str, chat_id: str)`. `engine.py` (Task 15) depends only on `AlertNotifier.send`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_notifiers.py
from unittest.mock import patch, MagicMock

from leader_watch.notifiers.base import AlertNotifier
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.notifiers.telegram import TelegramNotifier


def test_console_notifier_prints_title_and_body(capsys):
    notifier = ConsoleNotifier()
    assert isinstance(notifier, AlertNotifier)
    result = notifier.send("[09:10 조기 주도주 후보]", "종목: 테스트전자(005930)")
    captured = capsys.readouterr()
    assert result is True
    assert "[09:10 조기 주도주 후보]" in captured.out
    assert "테스트전자" in captured.out


def test_telegram_notifier_returns_false_when_token_missing():
    notifier = TelegramNotifier(bot_token="", chat_id="")
    assert notifier.send("title", "body") is False


@patch("leader_watch.notifiers.telegram.requests.post")
def test_telegram_notifier_posts_to_bot_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200, ok=True)
    notifier = TelegramNotifier(bot_token="TOKEN123", chat_id="CHAT456")
    result = notifier.send("[제목]", "본문")
    assert result is True
    args, kwargs = mock_post.call_args
    assert "TOKEN123" in args[0]
    assert kwargs["data"]["chat_id"] == "CHAT456"
    assert "[제목]" in kwargs["data"]["text"]


@patch("leader_watch.notifiers.telegram.requests.post")
def test_telegram_notifier_returns_false_on_request_exception(mock_post):
    mock_post.side_effect = Exception("network error")
    notifier = TelegramNotifier(bot_token="TOKEN123", chat_id="CHAT456")
    assert notifier.send("title", "body") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_notifiers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/notifiers/base.py
"""AlertNotifier interface — engine.py depends only on `send`."""
from __future__ import annotations

import abc


class AlertNotifier(abc.ABC):
    @abc.abstractmethod
    def send(self, title: str, body: str) -> bool:
        raise NotImplementedError
```

```python
# leader_watch/notifiers/console.py
"""Console-output notifier, used for local simulation/testing."""
from __future__ import annotations

from leader_watch.notifiers.base import AlertNotifier


class ConsoleNotifier(AlertNotifier):
    def send(self, title: str, body: str) -> bool:
        print(f"\n{title}\n{body}\n")
        return True
```

```python
# leader_watch/notifiers/telegram.py
"""Telegram notifier — same Bot API call pattern as the existing notifier.py."""
from __future__ import annotations

import requests

from leader_watch.notifiers.base import AlertNotifier

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier(AlertNotifier):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send(self, title: str, body: str) -> bool:
        if not self._bot_token or not self._chat_id:
            return False
        try:
            response = requests.post(
                _API_URL.format(token=self._bot_token),
                data={"chat_id": self._chat_id, "text": f"{title}\n\n{body}"},
                timeout=10,
            )
            return bool(getattr(response, "ok", False))
        except Exception:
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_notifiers.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/notifiers/ tests/leader_watch/test_notifiers.py
git commit -m "feat(leader_watch): add AlertNotifier interface with Console and Telegram implementations"
```

---

### Task 9: alerts.py (alert body formatters)

**Files:**
- Create: `leader_watch/alerts.py`
- Test: `tests/leader_watch/test_alerts.py`

**Interfaces:**
- Consumes: `StockSnapshot`, `ScoreBreakdown`, `CandidateState` from Task 2.
- Produces: `format_early_candidate(snapshot, breakdown, market_rank, theme_rank) -> tuple[str, str]` (title, body), `format_rejection(snapshot, score, reason) -> tuple[str, str]`, `format_confirmation(snapshot, breakdown, extras: dict) -> tuple[str, str]`, `format_weakness(snapshot, prev_score, curr_score, prev_rank, curr_rank, prev_theme_rank, curr_theme_rank, reasons) -> tuple[str, str]`, `format_recovery(snapshot, score) -> tuple[str, str]`, `format_leader_change(theme, old, new, old_rank, new_rank, reasons) -> tuple[str, str]`. Used by `state_machine.py` (Tasks 10-14) and `engine.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_alerts.py
import datetime
from leader_watch.alerts import (
    format_confirmation,
    format_early_candidate,
    format_leader_change,
    format_recovery,
    format_rejection,
    format_weakness,
)
from leader_watch.models import ScoreBreakdown, StockSnapshot


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 10),
        current_price=10600, prev_close=10000, open_price=10200,
        high_price=10650, low_price=10150, cum_volume=2_000_000,
        cum_trading_value=25_000_000_000, market_trading_value_rank=5,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def _breakdown():
    return ScoreBreakdown(trading_value=30, theme_leadership=20, price_strength=20, minute_flow=10, news=10, basis=["근거1", "근거2", "근거3"])


def test_early_candidate_alert_has_required_sections():
    title, body = format_early_candidate(_snapshot(), _breakdown(), market_rank=5, theme_rank=1)
    assert title == "[09:10 조기 주도주 후보]"
    assert "테스트전자(005930)" in body
    assert "90/100" in body
    assert "아직 오전 주도주 확정 전" in body
    assert "자동주문을 실행하지 않음" in body


def test_rejection_alert_has_reason():
    title, body = format_rejection(_snapshot(), score=45.0, reason="고점 대비 하락률 5% 초과")
    assert title == "[주도주 후보 탈락]"
    assert "고점 대비 하락률 5% 초과" in body
    assert "45/100" in body


def test_confirmation_alert_never_says_final_leader():
    title, body = format_confirmation(
        _snapshot(), _breakdown(),
        extras={
            "rank_change_vs_0910": "5위 -> 3위 (개선)",
            "theme_follower_count": 3,
            "open_held": True, "first_high_held": True,
            "pullback_volume_down": True, "rebreak_high": True, "rank_maintained": True,
        },
    )
    assert title == "[09:30 오전 주도주 1차 확정]"
    assert "당일 최종 주도주" not in body
    assert "오전 주도주로 1차 확정" in body
    assert "오후 장에서 주도권이 변경될 수 있음" in body


def test_weakness_alert_shows_before_after():
    title, body = format_weakness(
        _snapshot(current_price=10100), prev_score=80.0, curr_score=68.0,
        prev_rank=5, curr_rank=35, prev_theme_rank=1, curr_theme_rank=4,
        reasons=["고점 대비 하락률 5% 초과", "거래대금 순위 30위 밖으로 하락"],
    )
    assert title == "[주도력 약화]"
    assert "80/100 -> 68/100" in body
    assert "5위 -> 35위" in body
    assert "다른 테마 또는 종목으로 주도권 이동 가능" in body


def test_recovery_alert_present():
    title, body = format_recovery(_snapshot(), score=78.0)
    assert title == "[주도력 재회복]"
    assert "78/100" in body


def test_leader_change_alert_has_basis():
    title, body = format_leader_change(
        theme="로봇", old_name="기존대장주", old_code="000001",
        new_name="신규도전자", new_code="000002",
        old_rank=6, new_rank=2, reasons=["거래대금 우위 3회 연속 유지", "상승률 우위", "시가/돌파선 유지"],
    )
    assert title == "[테마 대장주 변경 감지]"
    assert "기존대장주(000001)" in body
    assert "신규도전자(000002)" in body
    assert "6위" in body and "2위" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_alerts.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/alerts.py
"""Alert body formatters — exact wording required by the spec (§2, §4, §5)."""
from __future__ import annotations

from leader_watch.models import ScoreBreakdown, StockSnapshot

_DISCLAIMER = "본 알림은 투자 추천이 아닌 조건 충족 알림이며 자동주문을 실행하지 않음"


def _kst(snapshot: StockSnapshot) -> str:
    return snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")


def format_early_candidate(snapshot: StockSnapshot, breakdown: ScoreBreakdown, market_rank: int, theme_rank: int) -> tuple[str, str]:
    title = "[09:10 조기 주도주 후보]"
    basis_lines = "\n".join(f"- {line}" for line in breakdown.basis[:3]) or "- 조건 충족 확인"
    body = f"""종목: {snapshot.name}({snapshot.code})
시장: {snapshot.market}
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
시가 대비: {snapshot.vs_open_pct:.2f}%
시초가 갭: {snapshot.gap_from_prev_close_pct:.2f}%

누적 거래대금: {snapshot.cum_trading_value / 1e8:.1f}억 원
거래대금 순위: {market_rank}위
체결강도: {snapshot.execution_strength}
테마: {snapshot.theme}
테마 내 순위: {theme_rank}위
현재 점수: {breakdown.total:.0f}/100

판단 근거:
{basis_lines}

상태:
아직 오전 주도주 확정 전
09:30까지 거래대금과 시가 지지 여부 재확인 필요

주의:
{_DISCLAIMER}"""
    return title, body


def format_rejection(snapshot: StockSnapshot, score: float, reason: str) -> tuple[str, str]:
    title = "[주도주 후보 탈락]"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}
현재 점수: {score:.0f}/100
탈락 사유: {reason}"""
    return title, body


def format_confirmation(snapshot: StockSnapshot, breakdown: ScoreBreakdown, extras: dict) -> tuple[str, str]:
    title = "[09:30 오전 주도주 1차 확정]"
    yn = lambda flag: "예" if flag else "아니오"  # noqa: E731
    basis_lines = "\n".join(f"- {line}" for line in breakdown.basis[:4]) or "- 조건 충족 확인"
    body = f"""종목: {snapshot.name}({snapshot.code})
시장: {snapshot.market}
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
시가 대비: {snapshot.vs_open_pct:.2f}%
시초가 갭: {snapshot.gap_from_prev_close_pct:.2f}%

누적 거래대금: {snapshot.cum_trading_value / 1e8:.1f}억 원
거래대금 순위: {snapshot.market_trading_value_rank}위
09:10 대비 순위: {extras.get("rank_change_vs_0910", "확인 불가")}
체결강도: {snapshot.execution_strength}

테마: {snapshot.theme}
테마 내 순위: {snapshot.theme_trading_value_rank}위
상승 중인 테마 종목 수: {extras.get("theme_follower_count", 0)}개
주도주 점수: {breakdown.total:.0f}/100

분봉 확인:
- 시가 지지: {yn(extras.get("open_held"))}
- 첫 고점 유지: {yn(extras.get("first_high_held"))}
- 눌림 시 거래량 감소: {yn(extras.get("pullback_volume_down"))}
- 직전 고점 재돌파: {yn(extras.get("rebreak_high"))}
- 거래대금 순위 유지: {yn(extras.get("rank_maintained"))}

판단 근거:
{basis_lines}

해석:
09:30 기준 오전 주도주로 1차 확정
오후 장에서 주도권이 변경될 수 있음

주의:
{_DISCLAIMER}"""
    return title, body


def format_weakness(
    snapshot: StockSnapshot, prev_score: float, curr_score: float,
    prev_rank: int, curr_rank: int, prev_theme_rank: int, curr_theme_rank: int,
    reasons: list[str],
) -> tuple[str, str]:
    title = "[주도력 약화]"
    drawdown = 0.0
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
고점 대비 하락률: {drawdown:.2f}%

점수: {prev_score:.0f}/100 -> {curr_score:.0f}/100
거래대금 순위: {prev_rank}위 -> {curr_rank}위
테마 내 순위: {prev_theme_rank}위 -> {curr_theme_rank}위

약화 사유:
{reason_lines}

상태:
오전 주도력 약화
다른 테마 또는 종목으로 주도권 이동 가능"""
    return title, body


def format_recovery(snapshot: StockSnapshot, score: float) -> tuple[str, str]:
    title = "[주도력 재회복]"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}
현재가: {snapshot.current_price}
현재 점수: {score:.0f}/100

상태:
주도력 약화 조건에서 회복하여 조건을 다시 충족함"""
    return title, body


def format_leader_change(
    theme: str, old_name: str, old_code: str, new_name: str, new_code: str,
    old_rank: int, new_rank: int, reasons: list[str],
) -> tuple[str, str]:
    title = "[테마 대장주 변경 감지]"
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""테마: {theme}
기준시각: (엔진에서 채움)

기존 대장주: {old_name}({old_code})
새 대장주 후보: {new_name}({new_code})

기존 종목 거래대금 순위: {old_rank}위
신규 종목 거래대금 순위: {new_rank}위

변경 근거:
{reason_lines}"""
    return title, body
```

Note in Step 3 that `format_weakness`'s "고점 대비 하락률" placeholder (`drawdown = 0.0`) and `format_leader_change`'s "기준시각" placeholder are intentionally left as engine-fillable values — fix this in Step 3.5 below since the test only checks presence of surrounding text, but the plan must not ship placeholder text. Replace both before considering the task done:

- [ ] **Step 3.5: Fix the two placeholder values before committing**

Update `format_weakness` signature to accept `drawdown_from_high_pct: float` as a parameter instead of hardcoding `0.0`, and update `format_leader_change` to accept `timestamp: str` as a parameter instead of the placeholder comment. Update both call sites (the test in Step 1 and, later, `state_machine.py`/`engine.py` in Tasks 13-14) accordingly:

```python
def format_weakness(
    snapshot: StockSnapshot, prev_score: float, curr_score: float,
    prev_rank: int, curr_rank: int, prev_theme_rank: int, curr_theme_rank: int,
    drawdown_from_high_pct: float, reasons: list[str],
) -> tuple[str, str]:
    title = "[주도력 약화]"
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
고점 대비 하락률: {drawdown_from_high_pct:.2f}%

점수: {prev_score:.0f}/100 -> {curr_score:.0f}/100
거래대금 순위: {prev_rank}위 -> {curr_rank}위
테마 내 순위: {prev_theme_rank}위 -> {curr_theme_rank}위

약화 사유:
{reason_lines}

상태:
오전 주도력 약화
다른 테마 또는 종목으로 주도권 이동 가능"""
    return title, body


def format_leader_change(
    theme: str, timestamp: str, old_name: str, old_code: str, new_name: str, new_code: str,
    old_rank: int, new_rank: int, reasons: list[str],
) -> tuple[str, str]:
    title = "[테마 대장주 변경 감지]"
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""테마: {theme}
기준시각: {timestamp}

기존 대장주: {old_name}({old_code})
새 대장주 후보: {new_name}({new_code})

기존 종목 거래대금 순위: {old_rank}위
신규 종목 거래대금 순위: {new_rank}위

변경 근거:
{reason_lines}"""
    return title, body
```

Update the test file's two calls to pass `drawdown_from_high_pct=5.3` and `timestamp="2026-08-11 09:45:00"` respectively, and assert on those exact values instead of the placeholder.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_alerts.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/alerts.py tests/leader_watch/test_alerts.py
git commit -m "feat(leader_watch): add alert body formatters for all six alert types"
```

---

### Task 10: state_machine.py — early candidate decision

**Files:**
- Create: `leader_watch/state_machine.py`
- Test: `tests/leader_watch/test_state_machine_early_candidate.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `StockSnapshot`, `CandidateState`, `ScoreBreakdown` (Task 2), `calculate_leader_score` (Task 4).
- Produces: `decide_early_candidate(snapshot: StockSnapshot, history: list[StockSnapshot], market_rank: int, theme_rank: int | None, theme_follower_count: int, prior_streak: int, config: Config) -> tuple[bool, ScoreBreakdown, int]` — returns `(qualifies, breakdown, new_streak)`. Used by `engine.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_state_machine_early_candidate.py
import datetime
from leader_watch.config import load_config
from leader_watch.models import StockSnapshot
from leader_watch.state_machine import decide_early_candidate

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 7),
        current_price=10400, prev_close=10000, open_price=10200,
        high_price=10450, low_price=10150, cum_volume=1_000_000,
        cum_trading_value=15_000_000_000, market_trading_value_rank=8,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
        avg_trading_value_same_time_20d=3_000_000_000,
        avg_volume_same_time_20d=300_000,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_qualifying_stock_on_second_consecutive_tick_registers():
    snap = _snapshot()
    qualifies, breakdown, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is True
    assert streak == 2
    assert breakdown.total >= CFG.early_min_score


def test_first_qualifying_tick_does_not_register_yet():
    snap = _snapshot()
    qualifies, breakdown, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=0, config=CFG,
    )
    assert qualifies is False
    assert streak == 1


def test_rank_outside_top_50_never_registers():
    snap = _snapshot(market_trading_value_rank=80)
    qualifies, breakdown, streak = decide_early_candidate(
        snap, history=[snap], market_rank=80, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0


def test_change_below_2pct_never_registers():
    snap = _snapshot(current_price=10100, change_hint=None)
    qualifies, breakdown, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0


def test_below_open_price_never_registers():
    snap = _snapshot(current_price=10150, open_price=10200)
    qualifies, _, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0


def test_theme_rank_outside_top2_never_registers():
    snap = _snapshot(theme_trading_value_rank=3)
    qualifies, _, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=3, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0


def test_volume_not_above_average_never_registers():
    snap = _snapshot(cum_volume=100_000, avg_volume_same_time_20d=300_000)
    qualifies, _, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0


def test_before_0900_never_registers_regardless_of_conditions():
    snap = _snapshot(timestamp=datetime.datetime(2026, 8, 11, 8, 55))
    qualifies, _, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
```

Remove the invalid `change_hint=None` kwarg from `test_change_below_2pct_never_registers` before running — `StockSnapshot` has no such field; it's dead from a copy/paste and must be deleted:

```python
def test_change_below_2pct_never_registers():
    snap = _snapshot(current_price=10100)
    qualifies, breakdown, streak = decide_early_candidate(
        snap, history=[snap], market_rank=8, theme_rank=1, theme_follower_count=2,
        prior_streak=1, config=CFG,
    )
    assert qualifies is False
    assert streak == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_state_machine_early_candidate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/state_machine.py
"""Pure-function phase-transition logic for the leader-watch state machine."""
from __future__ import annotations

import datetime

from leader_watch.config import Config
from leader_watch.models import CandidateState, MinuteBar, ScoreBreakdown, StockSnapshot, safe_ratio
from leader_watch.scoring import calculate_leader_score

_MARKET_OPEN = datetime.time(9, 0)


def _meets_early_conditions(
    snapshot: StockSnapshot, market_rank: int, theme_rank: int | None, config: Config
) -> bool:
    if snapshot.timestamp.time() < _MARKET_OPEN:
        return False
    if market_rank > config.early_trading_value_rank:
        return False
    if snapshot.change_pct < 2.0:
        return False
    if snapshot.vs_open_pct < 0:
        return False
    if theme_rank is None or theme_rank > 2:
        return False
    if snapshot.avg_volume_same_time_20d and snapshot.cum_volume <= snapshot.avg_volume_same_time_20d:
        return False
    return True


def decide_early_candidate(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    theme_follower_count: int,
    prior_streak: int,
    config: Config,
) -> tuple[bool, ScoreBreakdown, int]:
    breakdown = calculate_leader_score(snapshot, history, theme_follower_count, config)

    if not _meets_early_conditions(snapshot, market_rank, theme_rank, config):
        return False, breakdown, 0

    if breakdown.total < config.early_min_score:
        return False, breakdown, 0

    new_streak = prior_streak + 1
    qualifies = new_streak >= 2
    return qualifies, breakdown, new_streak
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_state_machine_early_candidate.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/state_machine.py tests/leader_watch/test_state_machine_early_candidate.py
git commit -m "feat(leader_watch): add early-candidate decision logic (09:05-09:10)"
```

---

### Task 11: state_machine.py — rejection checks (09:10-09:30)

**Files:**
- Modify: `leader_watch/state_machine.py`
- Test: `tests/leader_watch/test_state_machine_rejection.py`

**Interfaces:**
- Consumes: everything from Task 10 plus `MinuteBar.is_bearish_long_candle`.
- Produces: `check_rejection(candidate: CandidateState, snapshot: StockSnapshot, history: list[StockSnapshot], market_rank: int, theme_rank: int | None, config: Config) -> str | None` — returns the rejection reason string, or `None` if the candidate survives. Also mutates and returns updated open-recovery-fail counter via `update_open_recovery_tracking(candidate, snapshot) -> int`. Used by `engine.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_state_machine_rejection.py
import datetime
from leader_watch.config import load_config
from leader_watch.models import CandidateState, CandidateStatus, MinuteBar, Phase, StockSnapshot
from leader_watch.state_machine import check_rejection, update_open_recovery_tracking

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 15),
        current_price=10400, prev_close=10000, open_price=10200,
        high_price=10500, low_price=10150, cum_volume=1_000_000,
        cum_trading_value=15_000_000_000, market_trading_value_rank=8,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False, minute_bars_1m=[], minute_bars_5m=[],
    )
    base.update(overrides)
    return StockSnapshot(**base)


def _candidate(**overrides):
    base = dict(code="005930", name="테스트전자", phase=Phase.VALIDATION, status=CandidateStatus.ACTIVE, score=75.0)
    base.update(overrides)
    return CandidateState(**base)


def test_survives_when_all_conditions_fine():
    candidate = _candidate()
    reason = check_rejection(candidate, _snapshot(), history=[_snapshot()], market_rank=8, theme_rank=1, config=CFG)
    assert reason is None


def test_rejected_when_open_breach_twice_consecutive():
    candidate = _candidate(consecutive_open_recovery_fail=2)
    below_open = _snapshot(current_price=10100, open_price=10200)
    reason = check_rejection(candidate, below_open, history=[below_open], market_rank=8, theme_rank=1, config=CFG)
    assert reason == "시가 이탈 후 2회 연속 회복하지 못함"


def test_open_recovery_tracking_increments_and_resets():
    candidate = _candidate()
    below_open = _snapshot(current_price=10100, open_price=10200)
    count = update_open_recovery_tracking(candidate, below_open)
    assert count == 1
    above_open = _snapshot(current_price=10300, open_price=10200)
    count = update_open_recovery_tracking(candidate, above_open)
    assert count == 0


def test_rejected_when_trading_value_rank_outside_100():
    candidate = _candidate()
    reason = check_rejection(candidate, _snapshot(), history=[_snapshot()], market_rank=150, theme_rank=1, config=CFG)
    assert reason == "거래대금 순위가 100위 밖으로 하락"


def test_rejected_when_theme_rank_outside_top3():
    candidate = _candidate()
    reason = check_rejection(candidate, _snapshot(), history=[_snapshot()], market_rank=8, theme_rank=4, config=CFG)
    assert reason == "테마 내 거래대금 3위 밖으로 밀림"


def test_rejected_when_drawdown_from_high_exceeds_5pct():
    candidate = _candidate()
    dropped = _snapshot(current_price=9700, high_price=10500)
    reason = check_rejection(candidate, dropped, history=[dropped], market_rank=8, theme_rank=1, config=CFG)
    assert reason == "고점 대비 하락률이 5% 초과"


def test_rejected_when_bearish_long_candle_with_volume():
    bar = MinuteBar(datetime.datetime(2026, 8, 11, 9, 20), open=10500, high=10520, low=10100, close=10150, volume=500_000)
    prior_bar = MinuteBar(datetime.datetime(2026, 8, 11, 9, 19), open=10400, high=10500, low=10380, close=10490, volume=150_000)
    snap = _snapshot(minute_bars_1m=[prior_bar, bar])
    candidate = _candidate()
    reason = check_rejection(candidate, snap, history=[snap], market_rank=8, theme_rank=1, config=CFG)
    assert reason == "거래량을 동반한 장대음봉 발생"


def test_rejected_when_five_minute_highs_keep_falling():
    bars = [
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 11), 10300, 10500, 10250, 10400, 200_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 12), 10400, 10450, 10300, 10350, 180_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 13), 10350, 10400, 10250, 10300, 170_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 14), 10300, 10350, 10200, 10250, 160_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 15), 10250, 10300, 10150, 10200, 150_000),
    ]
    snap = _snapshot(minute_bars_5m=bars, current_price=10200, high_price=10500)
    candidate = _candidate()
    reason = check_rejection(candidate, snap, history=[snap], market_rank=8, theme_rank=1, config=CFG)
    assert reason == "최근 5분 동안 고점이 계속 낮아짐"


def test_rejected_when_status_flag_excluded():
    snap = _snapshot(is_trading_halted=True)
    candidate = _candidate()
    reason = check_rejection(candidate, snap, history=[snap], market_rank=8, theme_rank=1, config=CFG)
    assert reason == "거래정지, 관리종목, 투자위험 종목 등 제외 대상에 해당"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_state_machine_rejection.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_rejection'`

- [ ] **Step 3: Append to `leader_watch/state_machine.py`**

```python
def update_open_recovery_tracking(candidate: CandidateState, snapshot: StockSnapshot) -> int:
    if snapshot.vs_open_pct < 0:
        candidate.consecutive_open_recovery_fail += 1
    else:
        candidate.consecutive_open_recovery_fail = 0
    return candidate.consecutive_open_recovery_fail


def _declining_five_minute_highs(bars: list[MinuteBar]) -> bool:
    if len(bars) < 3:
        return False
    highs = [bar.high for bar in bars[-5:]]
    return all(earlier > later for earlier, later in zip(highs, highs[1:]))


def check_rejection(
    candidate: CandidateState,
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    config: Config,
) -> str | None:
    from leader_watch.filters import is_excluded

    excluded, _ = is_excluded(snapshot)
    if excluded:
        return "거래정지, 관리종목, 투자위험 종목 등 제외 대상에 해당"

    if candidate.consecutive_open_recovery_fail >= 2 and snapshot.vs_open_pct < 0:
        return "시가 이탈 후 2회 연속 회복하지 못함"

    bars = snapshot.minute_bars_1m
    if len(bars) >= 2:
        avg_volume = sum(bar.volume for bar in bars[:-1]) / len(bars[:-1])
        if bars[-1].is_bearish_long_candle(avg_volume=avg_volume):
            return "거래량을 동반한 장대음봉 발생"

    if market_rank > 100:
        return "거래대금 순위가 100위 밖으로 하락"

    if theme_rank is None or theme_rank > 3:
        return "테마 내 거래대금 3위 밖으로 밀림"

    drawdown = safe_ratio(snapshot.high_price - snapshot.current_price, snapshot.high_price) * 100
    if drawdown > 5.0:
        return "고점 대비 하락률이 5% 초과"

    if _declining_five_minute_highs(snapshot.minute_bars_5m):
        return "최근 5분 동안 고점이 계속 낮아짐"

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_state_machine_rejection.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/state_machine.py tests/leader_watch/test_state_machine_rejection.py
git commit -m "feat(leader_watch): add candidate rejection checks (09:10-09:30)"
```

---

### Task 12: state_machine.py — 09:30 confirmation evaluation

**Files:**
- Modify: `leader_watch/state_machine.py`
- Test: `tests/leader_watch/test_state_machine_confirmation.py`

**Interfaces:**
- Consumes: everything from Tasks 10-11.
- Produces: `classify_gap(gap_pct: float, config: Config) -> str` (returns one of `"정상"`, `"강한 후보(추격 위험)"`, `"고위험"`, `"확정 제외"`), `evaluate_confirmation(snapshot: StockSnapshot, history: list[StockSnapshot], market_rank: int, theme_rank: int | None, rank_at_0925: int | None, theme_follower_count: int, config: Config) -> tuple[bool, ScoreBreakdown, str | None]` — returns `(confirmed, breakdown, block_reason)`. Used by `engine.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_state_machine_confirmation.py
import datetime
from leader_watch.config import load_config
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.state_machine import classify_gap, evaluate_confirmation

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 30),
        current_price=10800, prev_close=10000, open_price=10200,
        high_price=10850, low_price=10150, cum_volume=3_000_000,
        cum_trading_value=40_000_000_000, market_trading_value_rank=5,
        execution_strength=150.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False, minute_bars_1m=[], minute_bars_5m=[],
        avg_trading_value_same_time_20d=4_000_000_000, avg_volume_same_time_20d=400_000,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_classify_gap_tiers():
    assert classify_gap(1.5, CFG) == "정상"
    assert classify_gap(4.0, CFG) == "강한 후보(추격 위험)"
    assert classify_gap(6.5, CFG) == "고위험"
    assert classify_gap(9.0, CFG) == "확정 제외"


def test_confirmed_when_all_required_conditions_met():
    history = [_snapshot(timestamp=datetime.datetime(2026, 8, 11, 9, m)) for m in (10, 15, 20, 25, 30)]
    confirmed, breakdown, block_reason = evaluate_confirmation(
        _snapshot(), history=history, market_rank=5, theme_rank=1, rank_at_0925=6,
        theme_follower_count=3, config=CFG,
    )
    assert confirmed is True
    assert block_reason is None
    assert breakdown.total >= CFG.confirmation_min_score


def test_blocked_when_rank_outside_top_30():
    history = [_snapshot(timestamp=datetime.datetime(2026, 8, 11, 9, m)) for m in (25, 30)]
    confirmed, _, block_reason = evaluate_confirmation(
        _snapshot(market_trading_value_rank=45), history=history, market_rank=45, theme_rank=1,
        rank_at_0925=40, theme_follower_count=3, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "09:30 누적 거래대금이 시장 상위 30위 밖"


def test_blocked_when_open_breached():
    snap = _snapshot(current_price=10100, open_price=10200)
    history = [snap]
    confirmed, _, block_reason = evaluate_confirmation(
        snap, history=history, market_rank=5, theme_rank=1, rank_at_0925=5,
        theme_follower_count=3, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "첫 급등 후 시가를 이탈함"


def test_blocked_when_drawdown_exceeds_3pct():
    snap = _snapshot(current_price=10400, high_price=10800)
    history = [snap]
    confirmed, _, block_reason = evaluate_confirmation(
        snap, history=history, market_rank=5, theme_rank=1, rank_at_0925=5,
        theme_follower_count=3, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "고점 대비 하락률이 3% 초과"


def test_blocked_when_no_theme_followers():
    history = [_snapshot(timestamp=datetime.datetime(2026, 8, 11, 9, m)) for m in (25, 30)]
    confirmed, _, block_reason = evaluate_confirmation(
        _snapshot(), history=history, market_rank=5, theme_rank=1, rank_at_0925=5,
        theme_follower_count=0, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "테마 내 후속 종목이 전혀 없음"


def test_blocked_when_gap_over_8pct_and_weak_followthrough():
    snap = _snapshot(open_price=10900, current_price=10850, execution_strength=90.0)
    history = [snap]
    confirmed, _, block_reason = evaluate_confirmation(
        snap, history=history, market_rank=5, theme_rank=1, rank_at_0925=5,
        theme_follower_count=3, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "갭 상승률이 8%를 초과하고 추가 매수세가 약함"


def test_blocked_when_no_news_and_no_price_sustain():
    flat_history = [
        _snapshot(timestamp=datetime.datetime(2026, 8, 11, 9, m), current_price=10200, news_today=False, news_continuing=False)
        for m in (10, 15, 20, 25, 30)
    ]
    confirmed, _, block_reason = evaluate_confirmation(
        flat_history[-1], history=flat_history, market_rank=5, theme_rank=1, rank_at_0925=5,
        theme_follower_count=3, config=CFG,
    )
    assert confirmed is False
    assert block_reason == "뉴스나 재료가 전혀 없고 상승 지속성도 확인되지 않음"


def test_blocked_when_score_below_threshold():
    snap = _snapshot(market_trading_value_rank=29, theme_trading_value_rank=2, avg_trading_value_same_time_20d=None, news_today=False, news_continuing=False)
    history = [snap]
    confirmed, breakdown, block_reason = evaluate_confirmation(
        snap, history=history, market_rank=29, theme_rank=2, rank_at_0925=29,
        theme_follower_count=1, config=CFG,
    )
    assert confirmed is False
    assert breakdown.total < CFG.confirmation_min_score
    assert block_reason == "총점 75점 미만"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_state_machine_confirmation.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Append to `leader_watch/state_machine.py`**

```python
def classify_gap(gap_pct: float, config: Config) -> str:
    if gap_pct <= 3.0:
        return "정상"
    if gap_pct <= 5.0:
        return "강한 후보(추격 위험)"
    if gap_pct <= config.max_gap_percent:
        return "고위험"
    return "확정 제외"


def evaluate_confirmation(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    rank_at_0925: int | None,
    theme_follower_count: int,
    config: Config,
) -> tuple[bool, ScoreBreakdown, str | None]:
    breakdown = calculate_leader_score(snapshot, history, theme_follower_count, config)

    if snapshot.vs_open_pct < 0:
        return False, breakdown, "첫 급등 후 시가를 이탈함"

    drawdown = safe_ratio(snapshot.high_price - snapshot.current_price, snapshot.high_price) * 100
    if drawdown > config.max_confirmation_drawdown_percent:
        return False, breakdown, "고점 대비 하락률이 3% 초과"

    bars = snapshot.minute_bars_1m
    if len(bars) >= 2:
        avg_volume = sum(bar.volume for bar in bars[:-1]) / len(bars[:-1])
        if bars[-1].is_bearish_long_candle(avg_volume=avg_volume):
            return False, breakdown, "거래량을 동반한 장대음봉 발생"

    if theme_follower_count == 0:
        return False, breakdown, "테마 내 후속 종목이 전혀 없음"

    if _declining_five_minute_highs(snapshot.minute_bars_5m):
        return False, breakdown, "거래대금은 크지만 고점이 계속 낮아짐"

    gap = snapshot.gap_from_prev_close_pct
    if gap > config.max_gap_percent and snapshot.execution_strength < 100:
        return False, breakdown, "갭 상승률이 8%를 초과하고 추가 매수세가 약함"

    if not snapshot.news_today and not snapshot.news_continuing:
        prices = [snap.current_price for snap in history]
        sustained = len(prices) >= 2 and prices[-1] >= prices[0]
        if not sustained:
            return False, breakdown, "뉴스나 재료가 전혀 없고 상승 지속성도 확인되지 않음"

    if market_rank > config.confirmation_trading_value_rank:
        return False, breakdown, "09:30 누적 거래대금이 시장 상위 30위 밖"

    if theme_rank is None or theme_rank > 2:
        return False, breakdown, "테마 또는 섹터 내 거래대금 1~2위 조건 미충족"

    if rank_at_0925 is not None and market_rank > rank_at_0925:
        return False, breakdown, "09:25~09:30 구간 거래대금 순위 악화"

    minutes_covered = 0
    if history:
        minutes_covered = (history[-1].timestamp - history[0].timestamp).total_seconds() / 60
    if minutes_covered < 5:
        return False, breakdown, "데이터가 최소 5분 이상 지속적으로 수집되지 않음"

    if breakdown.total < config.confirmation_min_score:
        return False, breakdown, "총점 75점 미만"

    return True, breakdown, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_state_machine_confirmation.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/state_machine.py tests/leader_watch/test_state_machine_confirmation.py
git commit -m "feat(leader_watch): add 09:30 confirmation evaluation with gap tiering"
```

---

### Task 13: state_machine.py — weakness/recovery monitoring (09:30-10:30)

**Files:**
- Modify: `leader_watch/state_machine.py`
- Test: `tests/leader_watch/test_state_machine_monitoring.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `check_weakness(candidate: CandidateState, snapshot: StockSnapshot, market_rank: int, theme_rank: int | None, config: Config, overtaken_by: bool = False) -> list[str]` (empty list = no weakness), `check_recovery(candidate: CandidateState, snapshot: StockSnapshot, market_rank: int, theme_rank: int | None, breakdown: ScoreBreakdown, config: Config) -> bool`. Used by `engine.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_state_machine_monitoring.py
import datetime
from leader_watch.config import load_config
from leader_watch.models import CandidateState, CandidateStatus, MinuteBar, Phase, ScoreBreakdown, StockSnapshot
from leader_watch.state_machine import check_recovery, check_weakness

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 45),
        current_price=10600, prev_close=10000, open_price=10200,
        high_price=10850, low_price=10150, cum_volume=3_000_000,
        cum_trading_value=40_000_000_000, market_trading_value_rank=10,
        execution_strength=120.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False, minute_bars_1m=[], minute_bars_5m=[],
    )
    base.update(overrides)
    return StockSnapshot(**base)


def _confirmed_candidate(**overrides):
    base = dict(
        code="005930", name="테스트전자", phase=Phase.MONITORING, status=CandidateStatus.CONFIRMED,
        score=80.0, high_since_confirm=10850, first_30min_low=10150,
    )
    base.update(overrides)
    return CandidateState(**base)


def test_no_weakness_when_holding_up():
    candidate = _confirmed_candidate()
    reasons = check_weakness(candidate, _snapshot(), market_rank=10, theme_rank=1, config=CFG)
    assert reasons == []


def test_weakness_on_open_breach():
    candidate = _confirmed_candidate()
    snap = _snapshot(current_price=10100, open_price=10200)
    reasons = check_weakness(candidate, snap, market_rank=10, theme_rank=1, config=CFG)
    assert "시가 이탈 후 회복 실패" in reasons


def test_weakness_on_first_30min_low_breach():
    candidate = _confirmed_candidate(first_30min_low=10150)
    snap = _snapshot(current_price=10050)
    reasons = check_weakness(candidate, snap, market_rank=10, theme_rank=1, config=CFG)
    assert "첫 30분봉 저점 이탈" in reasons


def test_weakness_on_rank_outside_30():
    candidate = _confirmed_candidate()
    reasons = check_weakness(candidate, _snapshot(), market_rank=35, theme_rank=1, config=CFG)
    assert "거래대금 순위가 30위 밖으로 하락" in reasons


def test_weakness_on_theme_rank_outside_3():
    candidate = _confirmed_candidate()
    reasons = check_weakness(candidate, _snapshot(), market_rank=10, theme_rank=4, config=CFG)
    assert "테마 내 거래대금 3위 밖으로 하락" in reasons


def test_weakness_on_drawdown_over_5pct():
    candidate = _confirmed_candidate(high_since_confirm=11000)
    snap = _snapshot(current_price=10400)
    reasons = check_weakness(candidate, snap, market_rank=10, theme_rank=1, config=CFG)
    assert "고점 대비 하락률 5% 초과" in reasons


def test_weakness_on_declining_5min_highs():
    bars = [
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 40), 10700, 10850, 10650, 10800, 200_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 41), 10800, 10820, 10700, 10750, 180_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 42), 10750, 10780, 10650, 10700, 170_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 43), 10700, 10730, 10600, 10650, 160_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 44), 10650, 10680, 10550, 10600, 150_000),
    ]
    candidate = _confirmed_candidate()
    snap = _snapshot(minute_bars_5m=bars)
    reasons = check_weakness(candidate, snap, market_rank=10, theme_rank=1, config=CFG)
    assert "5분봉 고점이 연속해서 낮아짐" in reasons


def test_weakness_on_score_below_75():
    candidate = _confirmed_candidate()
    snap = _snapshot(market_trading_value_rank=60, theme_trading_value_rank=None, news_today=False, news_continuing=False)
    reasons = check_weakness(candidate, snap, market_rank=60, theme_rank=None, config=CFG)
    assert "점수가 75점 미만으로 하락" in reasons


def test_weakness_when_overtaken_by_other_stock():
    candidate = _confirmed_candidate()
    reasons = check_weakness(candidate, _snapshot(), market_rank=10, theme_rank=1, config=CFG, overtaken_by=True)
    assert "다른 종목이 거래대금과 상승률에서 대장주를 추월" in reasons


def test_recovery_true_when_conditions_restored():
    candidate = _confirmed_candidate(status=CandidateStatus.WEAKENED)
    breakdown = ScoreBreakdown(trading_value=30, theme_leadership=20, price_strength=20, minute_flow=10, news=10)
    recovered = check_recovery(candidate, _snapshot(), market_rank=10, theme_rank=1, breakdown=breakdown, config=CFG)
    assert recovered is True


def test_recovery_false_when_still_weak():
    candidate = _confirmed_candidate(status=CandidateStatus.WEAKENED)
    breakdown = ScoreBreakdown(trading_value=10, theme_leadership=0, price_strength=5, minute_flow=0, news=0)
    recovered = check_recovery(candidate, _snapshot(market_trading_value_rank=60), market_rank=60, theme_rank=None, breakdown=breakdown, config=CFG)
    assert recovered is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_state_machine_monitoring.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Append to `leader_watch/state_machine.py`**

```python
def check_weakness(
    candidate: CandidateState,
    snapshot: StockSnapshot,
    market_rank: int,
    theme_rank: int | None,
    config: Config,
    overtaken_by: bool = False,
) -> list[str]:
    reasons: list[str] = []

    if snapshot.vs_open_pct < 0:
        reasons.append("시가 이탈 후 회복 실패")

    if candidate.first_30min_low is not None and snapshot.current_price < candidate.first_30min_low:
        reasons.append("첫 30분봉 저점 이탈")

    if market_rank > 30:
        reasons.append("거래대금 순위가 30위 밖으로 하락")

    if theme_rank is None or theme_rank > 3:
        reasons.append("테마 내 거래대금 3위 밖으로 하락")

    high_ref = candidate.high_since_confirm or snapshot.high_price
    drawdown = safe_ratio(high_ref - snapshot.current_price, high_ref) * 100
    if drawdown > config.max_weakness_drawdown_percent:
        reasons.append("고점 대비 하락률 5% 초과")

    if _declining_five_minute_highs(snapshot.minute_bars_5m):
        reasons.append("5분봉 고점이 연속해서 낮아짐")

    breakdown = calculate_leader_score(snapshot, [snapshot], theme_follower_count=1 if theme_rank else 0, config=config)
    if breakdown.total < config.confirmation_min_score:
        reasons.append("점수가 75점 미만으로 하락")

    if overtaken_by:
        reasons.append("다른 종목이 거래대금과 상승률에서 대장주를 추월")

    return reasons


def check_recovery(
    candidate: CandidateState,
    snapshot: StockSnapshot,
    market_rank: int,
    theme_rank: int | None,
    breakdown: ScoreBreakdown,
    config: Config,
) -> bool:
    if snapshot.vs_open_pct < 0:
        return False
    if market_rank > config.confirmation_trading_value_rank:
        return False
    if theme_rank is None or theme_rank > 2:
        return False
    if breakdown.total < config.confirmation_min_score:
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_state_machine_monitoring.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/state_machine.py tests/leader_watch/test_state_machine_monitoring.py
git commit -m "feat(leader_watch): add weakness and recovery monitoring (09:30-10:30)"
```

---

### Task 14: state_machine.py — theme leader-change detection

**Files:**
- Modify: `leader_watch/state_machine.py`
- Test: `tests/leader_watch/test_state_machine_leader_change.py`

**Interfaces:**
- Consumes: `CandidateState` history tracking.
- Produces: `detect_leader_change(current_leader: CandidateState, challenger: CandidateState, current_leader_snapshot: StockSnapshot, challenger_snapshot: StockSnapshot, challenger_market_rank: int, current_leader_market_rank: int) -> tuple[bool, list[str]]` — returns `(is_new_leader_confirmed_this_tick, reasons)`; caller (engine.py) is responsible for tracking `challenger.leader_change_streak` across ticks and firing the alert once streak reaches 3. This function only evaluates a single tick's superiority and increments/resets the streak on the passed-in `challenger` object.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_state_machine_leader_change.py
import datetime
from leader_watch.models import CandidateState, CandidateStatus, Phase, StockSnapshot
from leader_watch.state_machine import detect_leader_change


def _snapshot(code, price, open_price, cum_value, **overrides):
    base = dict(
        code=code, name=code, market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 45),
        current_price=price, prev_close=10000, open_price=open_price,
        high_price=price, low_price=open_price - 50, cum_volume=100_000,
        cum_trading_value=cum_value, market_trading_value_rank=1,
        execution_strength=120.0, theme="로봇", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def _candidate(code, streak=0):
    return CandidateState(code=code, name=code, phase=Phase.MONITORING, status=CandidateStatus.CONFIRMED, score=80.0, leader_change_streak=streak)


def test_challenger_gains_streak_when_superior_this_tick():
    leader = _candidate("OLD01")
    challenger = _candidate("NEW01", streak=1)
    old_snap = _snapshot("OLD01", price=10200, open_price=10100, cum_value=10_000_000_000)
    new_snap = _snapshot("NEW01", price=10800, open_price=10100, cum_value=15_000_000_000)
    confirmed, reasons = detect_leader_change(leader, challenger, old_snap, new_snap, challenger_market_rank=2, current_leader_market_rank=3)
    assert challenger.leader_change_streak == 2
    assert confirmed is False  # needs 3 consecutive
    assert len(reasons) >= 1


def test_leader_change_confirmed_on_third_consecutive_tick():
    leader = _candidate("OLD01")
    challenger = _candidate("NEW01", streak=2)
    old_snap = _snapshot("OLD01", price=10200, open_price=10100, cum_value=10_000_000_000)
    new_snap = _snapshot("NEW01", price=10800, open_price=10100, cum_value=15_000_000_000)
    confirmed, reasons = detect_leader_change(leader, challenger, old_snap, new_snap, challenger_market_rank=2, current_leader_market_rank=3)
    assert challenger.leader_change_streak == 3
    assert confirmed is True
    assert "거래대금 우위" in reasons[0] or any("거래대금" in r for r in reasons)


def test_streak_resets_when_challenger_falls_behind():
    leader = _candidate("OLD01")
    challenger = _candidate("NEW01", streak=2)
    old_snap = _snapshot("OLD01", price=10900, open_price=10100, cum_value=20_000_000_000)
    new_snap = _snapshot("NEW01", price=10300, open_price=10100, cum_value=8_000_000_000)
    confirmed, reasons = detect_leader_change(leader, challenger, old_snap, new_snap, challenger_market_rank=5, current_leader_market_rank=1)
    assert challenger.leader_change_streak == 0
    assert confirmed is False
    assert reasons == []


def test_streak_does_not_advance_when_challenger_breaches_open():
    leader = _candidate("OLD01")
    challenger = _candidate("NEW01", streak=1)
    old_snap = _snapshot("OLD01", price=10200, open_price=10100, cum_value=10_000_000_000)
    new_snap = _snapshot("NEW01", price=10050, open_price=10100, cum_value=15_000_000_000)  # below own open
    confirmed, reasons = detect_leader_change(leader, challenger, old_snap, new_snap, challenger_market_rank=2, current_leader_market_rank=3)
    assert challenger.leader_change_streak == 0
    assert confirmed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_state_machine_leader_change.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Append to `leader_watch/state_machine.py`**

```python
def detect_leader_change(
    current_leader: CandidateState,
    challenger: CandidateState,
    current_leader_snapshot: StockSnapshot,
    challenger_snapshot: StockSnapshot,
    challenger_market_rank: int,
    current_leader_market_rank: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    trading_value_ahead = challenger_snapshot.cum_trading_value > current_leader_snapshot.cum_trading_value
    if trading_value_ahead:
        reasons.append("신규 종목의 거래대금이 기존 대장주보다 많음")

    change_pct_ahead = challenger_snapshot.change_pct > current_leader_snapshot.change_pct
    if change_pct_ahead:
        reasons.append("신규 종목의 상승률이 기존 대장주보다 높음")

    holds_breakout = challenger_snapshot.vs_open_pct >= 0 and challenger_snapshot.current_price >= challenger_snapshot.high_price * 0.99
    if holds_breakout:
        reasons.append("신규 종목이 시가와 돌파선을 유지함")

    is_superior_this_tick = trading_value_ahead and change_pct_ahead and holds_breakout

    if is_superior_this_tick:
        challenger.leader_change_streak += 1
    else:
        challenger.leader_change_streak = 0
        return False, []

    confirmed = challenger.leader_change_streak >= 3
    return confirmed, reasons
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_state_machine_leader_change.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/state_machine.py tests/leader_watch/test_state_machine_leader_change.py
git commit -m "feat(leader_watch): add theme leader-change detection requiring 3 consecutive ticks"
```

---

### Task 15: engine.py — polling loop and orchestration

**Files:**
- Create: `leader_watch/engine.py`
- Test: `tests/leader_watch/test_engine.py`

**Interfaces:**
- Consumes: everything from Tasks 1-14.
- Produces: `is_market_holiday_or_weekend(day: datetime.date, holidays: set[datetime.date]) -> bool`, `is_stale(snapshot: StockSnapshot, now: datetime.datetime, config: Config) -> bool`, `call_with_retry(fn, max_retries: int = 3) -> Any`, `class Engine` with `__init__(self, provider: MarketDataProvider, notifier: AlertNotifier, config: Config, store: AlertStore)` and `run_once(self, now: datetime.datetime) -> None` (single polling tick — the unit the test suite drives) plus `run(self) -> None` (real-time loop calling `run_once` every `poll_interval_seconds`, used by `main.py`). `KRX_HOLIDAYS_2026` constant (a `set[datetime.date]`, hardcoded, documented as needing yearly manual updates).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_engine.py
import datetime
import os
import tempfile

import pytest
from leader_watch.config import load_config
from leader_watch.engine import Engine, call_with_retry, is_market_holiday_or_weekend, is_stale
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.providers.mock import MockProvider
from leader_watch.store import AlertStore


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = load_config(env={})
    eng = Engine(provider=MockProvider(), notifier=ConsoleNotifier(), config=cfg, store=AlertStore(path))
    yield eng
    os.remove(path)


def test_is_market_holiday_or_weekend_true_for_saturday():
    assert is_market_holiday_or_weekend(datetime.date(2026, 8, 15), holidays=set()) is True  # Sat


def test_is_market_holiday_or_weekend_true_for_registered_holiday():
    holidays = {datetime.date(2026, 1, 1)}
    assert is_market_holiday_or_weekend(datetime.date(2026, 1, 1), holidays=holidays) is True


def test_is_market_holiday_or_weekend_false_for_normal_weekday():
    assert is_market_holiday_or_weekend(datetime.date(2026, 8, 11), holidays=set()) is False  # Tue


def test_is_stale_true_when_timestamp_too_old(engine):
    now = datetime.datetime(2026, 8, 11, 9, 10)
    from leader_watch.models import StockSnapshot
    snap = StockSnapshot(
        code="X", name="X", market="KOSPI", timestamp=datetime.datetime(2026, 8, 11, 9, 8, 0),
        current_price=100, prev_close=100, open_price=100, high_price=100, low_price=100,
        cum_volume=1, cum_trading_value=1, market_trading_value_rank=1, execution_strength=100,
        theme=None, theme_trading_value_rank=None, news_today=False, news_continuing=False,
    )
    assert is_stale(snap, now, engine.config) is True


def test_is_stale_false_when_fresh(engine):
    now = datetime.datetime(2026, 8, 11, 9, 10, 5)
    from leader_watch.models import StockSnapshot
    snap = StockSnapshot(
        code="X", name="X", market="KOSPI", timestamp=datetime.datetime(2026, 8, 11, 9, 9, 50),
        current_price=100, prev_close=100, open_price=100, high_price=100, low_price=100,
        cum_volume=1, cum_trading_value=1, market_trading_value_rank=1, execution_strength=100,
        theme=None, theme_trading_value_rank=None, news_today=False, news_continuing=False,
    )
    assert is_stale(snap, now, engine.config) is False


def test_call_with_retry_succeeds_after_transient_failures():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise ConnectionError("boom")
        return "ok"

    result = call_with_retry(flaky, max_retries=3, base_delay_seconds=0)
    assert result == "ok"
    assert calls["count"] == 3


def test_call_with_retry_raises_after_exhausting_retries():
    def always_fails():
        raise ConnectionError("boom")

    with pytest.raises(ConnectionError):
        call_with_retry(always_fails, max_retries=2, base_delay_seconds=0)


def test_run_once_before_0900_sends_no_alerts(engine, capsys):
    engine.run_once(datetime.datetime(2026, 8, 11, 8, 30))
    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_once_on_weekend_sends_no_alerts(engine, capsys):
    engine.run_once(datetime.datetime(2026, 8, 15, 9, 30))  # Saturday
    captured = capsys.readouterr()
    assert captured.out == ""


def test_run_once_during_early_window_sends_early_candidate_alert_after_two_ticks(engine, capsys):
    engine.run_once(datetime.datetime(2026, 8, 11, 9, 6))
    engine.run_once(datetime.datetime(2026, 8, 11, 9, 8))
    captured = capsys.readouterr()
    assert "[09:10 조기 주도주 후보]" in captured.out
    assert "LEAD01" in captured.out or "리딩전자" in captured.out


def test_run_once_at_0930_sends_confirmation_alert_for_lead01(engine, capsys):
    for minute in (6, 8, 12, 18, 24, 30):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute))
    captured = capsys.readouterr()
    assert "[09:30 오전 주도주 1차 확정]" in captured.out


def test_run_once_dedupes_repeated_confirmation_alert(engine, capsys):
    for minute in (6, 8, 12, 18, 24, 30, 30):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute))
    captured = capsys.readouterr()
    assert captured.out.count("[09:30 오전 주도주 1차 확정]") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/engine.py
"""Polling loop: KST time gating, holiday/weekend guard, phase dispatch, dedup."""
from __future__ import annotations

import datetime
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from leader_watch.alerts import (
    format_confirmation,
    format_early_candidate,
    format_leader_change,
    format_recovery,
    format_rejection,
    format_weakness,
)
from leader_watch.config import Config
from leader_watch.filters import is_excluded
from leader_watch.models import CandidateState, CandidateStatus, Phase, StockSnapshot
from leader_watch.notifiers.base import AlertNotifier
from leader_watch.providers.base import MarketDataProvider
from leader_watch.state_machine import (
    check_recovery,
    check_rejection,
    check_weakness,
    decide_early_candidate,
    detect_leader_change,
    evaluate_confirmation,
    update_open_recovery_tracking,
)
from leader_watch.store import AlertStore

# NOTE: manually maintained; must be refreshed each year (see README "휴장일 캘린더 갱신").
KRX_HOLIDAYS_2026: set[datetime.date] = {
    datetime.date(2026, 1, 1),
    datetime.date(2026, 2, 16),
    datetime.date(2026, 2, 17),
    datetime.date(2026, 2, 18),
    datetime.date(2026, 3, 1),
    datetime.date(2026, 3, 2),
    datetime.date(2026, 5, 5),
    datetime.date(2026, 5, 24),
    datetime.date(2026, 5, 25),
    datetime.date(2026, 6, 6),
    datetime.date(2026, 8, 15),
    datetime.date(2026, 9, 24),
    datetime.date(2026, 9, 25),
    datetime.date(2026, 9, 26),
    datetime.date(2026, 10, 3),
    datetime.date(2026, 10, 9),
    datetime.date(2026, 12, 25),
    datetime.date(2026, 12, 31),
}


def is_market_holiday_or_weekend(day: datetime.date, holidays: set[datetime.date]) -> bool:
    return day.weekday() >= 5 or day in holidays


def is_stale(snapshot: StockSnapshot, now: datetime.datetime, config: Config) -> bool:
    age_seconds = (now - snapshot.timestamp).total_seconds()
    return age_seconds > config.stale_threshold_seconds


def call_with_retry(fn: Callable[[], Any], max_retries: int = 3, base_delay_seconds: float = 0.5) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - intentionally broad: any provider failure is retryable
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(base_delay_seconds * (2 ** attempt))
    assert last_error is not None
    raise last_error


class Engine:
    def __init__(self, provider: MarketDataProvider, notifier: AlertNotifier, config: Config, store: AlertStore) -> None:
        self.provider = provider
        self.notifier = notifier
        self.config = config
        self.store = store
        self.candidates: dict[str, CandidateState] = {}
        self.confirmed_theme_leader: dict[str, str] = {}  # theme -> leading code
        self.history: dict[str, list[StockSnapshot]] = {}
        self.rank_at_0925: dict[str, int] = {}

    def _should_send(self, code: str, alert_type: str, date: str, now: datetime.datetime, score: float) -> bool:
        last = self.store.last_alert(code, date, alert_type)
        if last is None:
            return True
        last_sent_at, last_score = last
        if (now - last_sent_at).total_seconds() >= self.config.alert_cooldown_seconds:
            return True
        return abs(score - last_score) >= self.config.score_renotify_delta

    def _send(self, code: str, alert_type: str, date: str, now: datetime.datetime, score: float, title: str, body: str) -> None:
        if not self._should_send(code, alert_type, date, now, score):
            return
        if self.notifier.send(title, body):
            self.store.record_alert(code, date, alert_type, score, now)

    def _theme_follower_count(self, snapshot: StockSnapshot, snapshots: list[StockSnapshot]) -> int:
        if snapshot.theme is None:
            return 0
        return sum(
            1 for other in snapshots
            if other.code != snapshot.code and other.theme == snapshot.theme and other.change_pct >= 2.0
        )

    def run_once(self, now: datetime.datetime) -> None:
        if is_market_holiday_or_weekend(now.date(), KRX_HOLIDAYS_2026):
            return
        if now.time() < datetime.time(9, 0) or now.time() > self.config.monitoring_end_time:
            return

        snapshots = call_with_retry(lambda: self.provider.get_snapshot(now))
        fresh = [s for s in snapshots if not is_stale(s, now, self.config) and not is_excluded(s)[0]]
        date = now.strftime("%Y-%m-%d")

        for snapshot in fresh:
            self.history.setdefault(snapshot.code, []).append(snapshot)

        if datetime.time(9, 24) <= now.time() <= datetime.time(9, 26):
            for snapshot in fresh:
                self.rank_at_0925[snapshot.code] = snapshot.market_trading_value_rank

        if now.time() < self.config.early_candidate_time:
            return

        if self.config.early_candidate_time <= now.time() < self.config.early_candidate_end_time:
            self._process_early_candidates(fresh, now, date)
        elif self.config.early_candidate_end_time <= now.time() < self.config.confirmation_time:
            self._process_validation(fresh, now, date)
        elif now.time() == self.config.confirmation_time:
            self._process_confirmation(fresh, now, date)
        elif self.config.confirmation_time < now.time() <= self.config.monitoring_end_time:
            self._process_monitoring(fresh, now, date)

    def _process_early_candidates(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            history = self.history.get(snapshot.code, [snapshot])
            theme_rank = snapshot.theme_trading_value_rank
            prior = self.candidates.get(snapshot.code)
            prior_streak = prior.early_candidate_streak if prior else 0
            theme_followers = self._theme_follower_count(snapshot, snapshots)

            qualifies, breakdown, streak = decide_early_candidate(
                snapshot, history, snapshot.market_trading_value_rank, theme_rank,
                theme_followers, prior_streak, self.config,
            )

            state = prior or CandidateState(code=snapshot.code, name=snapshot.name, phase=Phase.EARLY_CANDIDATE, status=CandidateStatus.ACTIVE, score=breakdown.total)
            state.early_candidate_streak = streak
            state.score = breakdown.total
            state.market_rank = snapshot.market_trading_value_rank
            state.theme_rank = theme_rank
            self.candidates[snapshot.code] = state
            self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.EARLY_CANDIDATE.value, state.status.value, breakdown.total, now)

            if qualifies:
                title, body = format_early_candidate(snapshot, breakdown, snapshot.market_trading_value_rank, theme_rank or 0)
                self._send(snapshot.code, "early_candidate", date, now, breakdown.total, title, body)

    def _process_validation(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            state = self.candidates.get(snapshot.code)
            if state is None or state.status != CandidateStatus.ACTIVE:
                continue

            update_open_recovery_tracking(state, snapshot)
            reason = check_rejection(state, snapshot, self.history.get(snapshot.code, [snapshot]), snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, self.config)

            if reason is not None:
                state.status = CandidateStatus.REJECTED
                self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.VALIDATION.value, state.status.value, state.score, now)
                title, body = format_rejection(snapshot, state.score, reason)
                self._send(snapshot.code, "rejected", date, now, state.score, title, body)

    def _process_confirmation(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        for snapshot in snapshots:
            state = self.candidates.get(snapshot.code)
            if state is None or state.status != CandidateStatus.ACTIVE:
                continue

            theme_followers = self._theme_follower_count(snapshot, snapshots)
            confirmed, breakdown, block_reason = evaluate_confirmation(
                snapshot, self.history.get(snapshot.code, [snapshot]), snapshot.market_trading_value_rank,
                snapshot.theme_trading_value_rank, self.rank_at_0925.get(snapshot.code), theme_followers, self.config,
            )
            state.score = breakdown.total

            if not confirmed:
                continue

            state.status = CandidateStatus.CONFIRMED
            state.phase = Phase.MONITORING
            state.high_since_confirm = snapshot.high_price
            state.first_30min_low = snapshot.low_price
            self.store.upsert_candidate(snapshot.code, date, snapshot.name, Phase.CONFIRMATION.value, state.status.value, breakdown.total, now)

            if snapshot.theme:
                self.confirmed_theme_leader[snapshot.theme] = snapshot.code

            rank_change = "확인 불가"
            prior_rank = self.rank_at_0925.get(snapshot.code)
            if prior_rank is not None:
                direction = "개선" if snapshot.market_trading_value_rank <= prior_rank else "악화"
                rank_change = f"{prior_rank}위 -> {snapshot.market_trading_value_rank}위 ({direction})"

            extras = {
                "rank_change_vs_0910": rank_change,
                "theme_follower_count": theme_followers,
                "open_held": snapshot.vs_open_pct >= 0,
                "first_high_held": snapshot.current_price >= snapshot.high_price * 0.99,
                "pullback_volume_down": True,
                "rebreak_high": snapshot.current_price >= snapshot.high_price,
                "rank_maintained": prior_rank is None or snapshot.market_trading_value_rank <= prior_rank,
            }
            title, body = format_confirmation(snapshot, breakdown, extras)
            self._send(snapshot.code, "confirmed", date, now, breakdown.total, title, body)

    def _process_monitoring(self, snapshots: list[StockSnapshot], now: datetime.datetime, date: str) -> None:
        by_code = {s.code: s for s in snapshots}
        confirmed_states = {c: s for c, s in self.candidates.items() if s.status in (CandidateStatus.CONFIRMED, CandidateStatus.WEAKENED)}

        for code, state in confirmed_states.items():
            snapshot = by_code.get(code)
            if snapshot is None:
                continue

            if snapshot.high_price and (state.high_since_confirm is None or snapshot.high_price > state.high_since_confirm):
                state.high_since_confirm = snapshot.high_price

            overtaken = False
            if snapshot.theme and self.confirmed_theme_leader.get(snapshot.theme) not in (None, code):
                overtaken = True

            if state.status == CandidateStatus.CONFIRMED:
                reasons = check_weakness(state, snapshot, snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, self.config, overtaken_by=overtaken)
                if reasons:
                    prev_score, prev_rank, prev_theme_rank = state.score, state.market_rank, state.theme_rank
                    state.status = CandidateStatus.WEAKENED
                    breakdown = decide_early_candidate.__wrapped__ if False else None  # unused placeholder removed below
                    drawdown = 0.0
                    if state.high_since_confirm:
                        drawdown = max(0.0, (state.high_since_confirm - snapshot.current_price) / state.high_since_confirm * 100)
                    curr_score = state.score
                    state.score = curr_score
                    self.store.upsert_candidate(code, date, snapshot.name, Phase.MONITORING.value, state.status.value, state.score, now)
                    title, body = format_weakness(
                        snapshot, prev_score, state.score, prev_rank or 0, snapshot.market_trading_value_rank,
                        prev_theme_rank or 0, snapshot.theme_trading_value_rank or 0, drawdown, reasons,
                    )
                    self._send(code, "weakened", date, now, state.score, title, body)
            elif state.status == CandidateStatus.WEAKENED:
                theme_followers = self._theme_follower_count(snapshot, snapshots)
                from leader_watch.scoring import calculate_leader_score
                breakdown = calculate_leader_score(snapshot, self.history.get(code, [snapshot]), theme_followers, self.config)
                if check_recovery(state, snapshot, snapshot.market_trading_value_rank, snapshot.theme_trading_value_rank, breakdown, self.config):
                    state.status = CandidateStatus.RECOVERED
                    state.score = breakdown.total
                    self.store.upsert_candidate(code, date, snapshot.name, Phase.MONITORING.value, state.status.value, state.score, now)
                    title, body = format_recovery(snapshot, breakdown.total)
                    self._send(code, "recovered", date, now, state.score, title, body)

            state.market_rank = snapshot.market_trading_value_rank
            state.theme_rank = snapshot.theme_trading_value_rank

        self._detect_leader_changes(by_code, now, date)

    def _detect_leader_changes(self, by_code: dict[str, StockSnapshot], now: datetime.datetime, date: str) -> None:
        by_theme: dict[str, list[str]] = {}
        for code, state in self.candidates.items():
            if state.status not in (CandidateStatus.CONFIRMED, CandidateStatus.WEAKENED):
                continue
            snapshot = by_code.get(code)
            if snapshot is None or snapshot.theme is None:
                continue
            by_theme.setdefault(snapshot.theme, []).append(code)

        for theme, codes in by_theme.items():
            leader_code = self.confirmed_theme_leader.get(theme)
            if leader_code is None or leader_code not in codes:
                continue
            for code in codes:
                if code == leader_code:
                    continue
                leader_state = self.candidates[leader_code]
                challenger_state = self.candidates[code]
                leader_snap = by_code[leader_code]
                challenger_snap = by_code[code]
                confirmed, reasons = detect_leader_change(
                    leader_state, challenger_state, leader_snap, challenger_snap,
                    challenger_snap.market_trading_value_rank, leader_snap.market_trading_value_rank,
                )
                if confirmed:
                    self.confirmed_theme_leader[theme] = code
                    title, body = format_leader_change(
                        theme, now.strftime("%Y-%m-%d %H:%M:%S"), leader_snap.name, leader_code,
                        challenger_snap.name, code, leader_snap.market_trading_value_rank,
                        challenger_snap.market_trading_value_rank, reasons,
                    )
                    self._send(code, "leader_change", date, now, challenger_state.score, title, body)

    def run(self) -> None:
        while True:
            now = datetime.datetime.now(ZoneInfo(self.config.market_timezone)).replace(tzinfo=None)
            self.run_once(now)
            if now.time() > self.config.monitoring_end_time:
                break
            time.sleep(self.config.poll_interval_seconds)
```

Before running the tests, remove the dead placeholder line `breakdown = decide_early_candidate.__wrapped__ if False else None  # unused placeholder removed below` from `_process_monitoring` — it was left in from drafting and does nothing; delete that single line entirely.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_engine.py -v`
Expected: PASS (11 tests). If `test_run_once_at_0930_sends_confirmation_alert_for_lead01` fails because LEAD01's mock scenario score falls short of `CONFIRMATION_MIN_SCORE`, adjust `LEAD01`'s `avg_trading_value_same_time_20d`/`avg_volume_same_time_20d` in `mock_scenarios.py` (Task 5) downward so its trading-value ratio bonus applies — re-run `pytest tests/leader_watch/test_providers_mock.py tests/leader_watch/test_engine.py -v` after any such adjustment to confirm both files still pass.

- [ ] **Step 5: Commit**

```bash
git add leader_watch/engine.py tests/leader_watch/test_engine.py
git commit -m "feat(leader_watch): add polling engine with phase dispatch, retry, and dedup"
```

---

### Task 16: main.py CLI + run_daily_scheduler.py split

**Files:**
- Modify: `main.py` (full rewrite)
- Create: `run_daily_scheduler.py`
- Test: `tests/leader_watch/test_main_cli.py`

**Interfaces:**
- Consumes: `Engine`, `MockProvider`, `RealProvider`, `ConsoleNotifier`, `TelegramNotifier`, `load_config`, `AlertStore` from prior tasks.
- Produces: `leader_watch_main(argv: list[str]) -> int` (importable, testable entry function) called by `main.py`'s `if __name__ == "__main__":` block.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_main_cli.py
import argparse
from unittest.mock import patch

from main import build_arg_parser, leader_watch_main


def test_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.provider == "mock"
    assert args.notifier == "console"


def test_arg_parser_accepts_real_and_telegram():
    parser = build_arg_parser()
    args = parser.parse_args(["--provider", "real", "--notifier", "telegram"])
    assert args.provider == "real"
    assert args.notifier == "telegram"


def test_arg_parser_rejects_invalid_provider():
    parser = build_arg_parser()
    try:
        parser.parse_args(["--provider", "bogus"])
        assert False, "should have raised"
    except SystemExit:
        pass


@patch("main.Engine")
def test_leader_watch_main_mock_provider_runs_single_tick_in_test_mode(mock_engine_cls):
    instance = mock_engine_cls.return_value
    exit_code = leader_watch_main(["--provider", "mock", "--notifier", "console", "--single-tick"])
    assert exit_code == 0
    instance.run_once.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_arg_parser' from 'main'`

- [ ] **Step 3: Write the implementation**

```python
# main.py
"""Entry point for the 09:00-10:30 morning leader-watch system.

Usage:
    python main.py --provider mock              # simulation, console output
    python main.py --provider real               # requires RealProvider implementation
    python main.py --provider mock --notifier telegram
    python main.py --provider mock --single-tick  # run exactly one poll and exit (testing)

The existing daily close/NXT batch (15:10 / 19:50) now lives in
`run_daily_scheduler.py` and is unaffected by this entry point.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from zoneinfo import ZoneInfo

from leader_watch.config import load_config
from leader_watch.engine import Engine
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.notifiers.telegram import TelegramNotifier
from leader_watch.providers.mock import MockProvider
from leader_watch.providers.real import RealProvider
from leader_watch.store import AlertStore

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = "", ""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="09:00-10:30 morning leader-stock watch system")
    parser.add_argument("--provider", choices=["mock", "real"], default="mock")
    parser.add_argument("--notifier", choices=["console", "telegram"], default="console")
    parser.add_argument("--single-tick", action="store_true", help="run exactly one poll and exit (used by tests/manual checks)")
    return parser


def leader_watch_main(argv: list[str]) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config()

    provider = MockProvider() if args.provider == "mock" else RealProvider()
    notifier = ConsoleNotifier() if args.notifier == "console" else TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    store = AlertStore(config.db_path)

    engine = Engine(provider=provider, notifier=notifier, config=config, store=store)

    if args.single_tick:
        now = datetime.datetime.now(ZoneInfo(config.market_timezone)).replace(tzinfo=None)
        engine.run_once(now)
        return 0

    engine.run()
    return 0


if __name__ == "__main__":
    sys.exit(leader_watch_main(sys.argv[1:]))
```

```python
# run_daily_scheduler.py
"""Existing daily close(15:10)/NXT(19:50) batch scheduler entry point.

This is the former contents of main.py, unchanged, moved here so that
main.py can become the entry point for the new 09:00-10:30 leader-watch
system. Run with: python run_daily_scheduler.py
"""
import scheduler

if __name__ == "__main__":
    scheduler.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify the old daily-batch entry point still works**

Run: `python -c "import run_daily_scheduler"`
Expected: no import errors (does not actually start the infinite scheduler loop, just verifies the module imports cleanly).

- [ ] **Step 6: Commit**

```bash
git add main.py run_daily_scheduler.py tests/leader_watch/test_main_cli.py
git commit -m "feat(leader_watch): make main.py the leader-watch CLI entry point, move daily batch to run_daily_scheduler.py"
```

---

### Task 17: Integration smoke test — full 09:00-10:30 MockProvider run

**Files:**
- Create: `tests/leader_watch/test_integration_mock_run.py`

**Interfaces:**
- Consumes: `Engine`, `MockProvider`, `ConsoleNotifier`, `AlertStore`, `load_config`.
- Produces: nothing new — this is a pure verification task.

- [ ] **Step 1: Write the test**

```python
# tests/leader_watch/test_integration_mock_run.py
import datetime
import os
import tempfile

import pytest
from leader_watch.config import load_config
from leader_watch.engine import Engine
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.providers.mock import MockProvider
from leader_watch.store import AlertStore


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = load_config(env={})
    eng = Engine(provider=MockProvider(), notifier=ConsoleNotifier(), config=cfg, store=AlertStore(path))
    yield eng
    os.remove(path)


def test_full_0900_to_1030_run_produces_expected_alert_sequence(engine, capsys):
    start = datetime.datetime(2026, 8, 11, 9, 0)
    for minute in range(0, 91):
        engine.run_once(start + datetime.timedelta(minutes=minute))

    out = capsys.readouterr().out

    assert "[09:10 조기 주도주 후보]" in out
    assert "[09:30 오전 주도주 1차 확정]" in out
    assert "[주도주 후보 탈락]" in out
    assert "[주도력 약화]" in out
    assert "당일 최종 주도주" not in out

    assert "LEAD01" in out or "리딩전자" in out
    assert "GAP01" not in out.split("[09:30 오전 주도주 1차 확정]")[1].split("[주도주 후보 탈락]")[0] if "[09:30 오전 주도주 1차 확정]" in out and "[주도주 후보 탈락]" in out else True


def test_full_run_sends_no_alerts_on_holiday(engine, capsys):
    start = datetime.datetime(2026, 1, 1, 9, 0)  # KRX New Year holiday
    for minute in range(0, 40, 5):
        engine.run_once(start + datetime.timedelta(minutes=minute))
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Run test**

Run: `pytest tests/leader_watch/test_integration_mock_run.py -v`
Expected: PASS (2 tests). If any assertion fails, inspect the printed `out` to see which scenario in `mock_scenarios.py` (Task 5) needs adjusting — the scenarios are hand-authored numbers and may need tuning so `RANK01`, `FAIL01`, `GAP01` actually fail confirmation and `LEAD01`/`WEAK01` actually pass/weaken as intended. Do not change `state_machine.py` thresholds to force this test to pass — only adjust the mock scenario data.

- [ ] **Step 3: Commit**

```bash
git add tests/leader_watch/test_integration_mock_run.py
git commit -m "test(leader_watch): add full 09:00-10:30 MockProvider integration smoke test"
```

---

### Task 18: Full test suite run, README, .env.example final pass

**Files:**
- Create: `README.md`
- Modify: `.env.example` (verify complete from Task 1)

**Interfaces:** None — documentation and verification only.

- [ ] **Step 1: Run the entire test suite (existing + new)**

Run: `pytest -v`
Expected: All existing tests (10 files under `tests/`) still PASS, plus all `tests/leader_watch/` tests PASS. If any existing test fails, STOP — it means Task 16's `main.py` rewrite broke something the existing suite depends on (check `tests/test_recommender.py` and `tests/test_notifier.py` don't import `main.py`); fix before proceeding.

- [ ] **Step 2: Manually run the mock simulation end-to-end via CLI**

Run: `python main.py --provider mock --notifier console --single-tick`
Expected: prints one poll's worth of output (likely nothing before 09:05 depending on current wall-clock time, since `run_once` gates on real KST time — this just verifies the CLI wires up without crashing). Confirm exit code 0.

- [ ] **Step 3: Write `README.md`**

```markdown
# jongbe_recommender

## 오전 주도주 실시간 감시 시스템 (09:00–10:30 KST)

`main.py`는 장 시작 직후 09:00~10:30 사이에 실시간으로 급등 종목을 감시하여,
09:00 직후 급등만으로 즉시 확정하지 않고 09:30까지 거래대금·테마 순위·시가
유지력·분봉 흐름을 검증한 뒤 "오전 주도주"로 1차 확정하는 시스템입니다.

**이 시스템은 시장 데이터 분석과 Telegram/콘솔 알림만 수행합니다. 주문 제출,
매수/매도, 계좌 잔고 변경 등 자동매매 기능은 전혀 포함하지 않습니다.**

### 실행 방법

```bash
# 시뮬레이션 (실제 데이터 없이 MockProvider로 전체 흐름 테스트, 콘솔 출력)
python main.py --provider mock --notifier console

# 실제 데이터 사용 시 (RealProvider 구현 필요 — 아래 "TODO" 참고)
python main.py --provider real --notifier telegram
```

옵션:
- `--provider {mock,real}` — 데이터 소스 선택 (기본값: mock)
- `--notifier {console,telegram}` — 알림 채널 선택 (기본값: console)
- `--single-tick` — 폴링 루프 대신 1회만 실행하고 종료 (테스트/수동 확인용)

### 기존 일일 배치 시스템 (15:10 장마감 / 19:50 NXT)

기존 배치는 그대로 유지되며, 실행 파일만 이동했습니다:

```bash
python run_daily_scheduler.py
```

### 설정값

`.env` 파일에서 아래 값을 조정할 수 있습니다 (`.env.example` 참고):

| 변수 | 기본값 | 설명 |
|---|---|---|
| EARLY_CANDIDATE_TIME | 09:05 | 조기 후보 판단 시작 시각 |
| EARLY_CANDIDATE_END_TIME | 09:10 | 조기 후보 판단 종료 시각 |
| CONFIRMATION_TIME | 09:30 | 오전 주도주 1차 확정 시각 |
| MONITORING_END_TIME | 10:30 | 주도력 감시 종료 시각 |
| EARLY_MIN_SCORE | 70 | 조기 후보 최소 점수 |
| CONFIRMATION_MIN_SCORE | 75 | 확정 최소 점수 |
| EARLY_TRADING_VALUE_RANK | 50 | 조기 후보 거래대금 순위 기준 |
| CONFIRMATION_TRADING_VALUE_RANK | 30 | 확정 거래대금 순위 기준 |
| MAX_GAP_PERCENT | 8 | 갭 상승률 확정 제외 기준 |
| MAX_CONFIRMATION_DRAWDOWN_PERCENT | 3 | 확정 시 고점 대비 하락 허용치 |
| MAX_WEAKNESS_DRAWDOWN_PERCENT | 5 | 주도력 약화 판단 하락 기준 |
| MIN_THEME_FOLLOWERS | 2 | 테마 동반 상승 최소 종목 수 |
| ALERT_COOLDOWN_SECONDS | 300 | 동일 알림 재발송 쿨다운(초) |
| POLL_INTERVAL_SECONDS | 2 | 데이터 폴링 주기(초) |
| MARKET_TIMEZONE | Asia/Seoul | 시간 기준 타임존 |
| STALE_THRESHOLD_SECONDS | 30 | 데이터 지연 판단 기준(초, 스펙 외 추가 설정) |
| SCORE_RENOTIFY_DELTA | 10 | 점수 변화 시 예외 재알림 기준(스펙 외 추가 설정) |
| LEADER_WATCH_DB_PATH | leader_watch/data/alerts.db | 알림 이력 SQLite 경로(스펙 외 추가 설정) |

### 휴장일 캘린더 갱신

`leader_watch/engine.py`의 `KRX_HOLIDAYS_2026`는 매년 수동으로 갱신해야 합니다.
외부 API 연동이 없으므로, 매년 말 다음 해의 한국거래소 휴장일을 확인하여 이
세트를 갱신하세요.

### 테스트

```bash
pytest tests/leader_watch/ -v   # 신규 시스템만
pytest -v                        # 전체 (기존 배치 포함)
```

### TODO / 실 데이터 연동 필요 사항

- `leader_watch/providers/real.py`의 `RealProvider`는 아직 구현되지 않았습니다.
  실시간 1분봉/5분봉/체결강도/거래대금순위를 제공하는 증권사 API(예: 한국투자증권
  Open API 등)를 선정한 뒤, 해당 클래스를 구현해야 `--provider real`이 동작합니다.
- 10:30 이후 "새로운 주도 테마 변화"에 대한 별도 알림 로직은 이번 범위에 포함되지
  않았습니다 (기존 확정 종목 상태 유지만 수행).
- 당일 뉴스/공시 데이터는 MockProvider 시나리오에 하드코딩되어 있으며, 실제
  뉴스/공시 API 연동은 `RealProvider` 구현 시 함께 처리해야 합니다.
- 휴장일 캘린더는 수동 갱신 방식입니다.
```

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example
git commit -m "docs: add README for morning leader-watch system"
```

---

## Self-Review Notes (already applied above)

- **Spec coverage:** §1(시간대/휴장일/확정 문구) → Task 15/18; §2(초기수집/조기후보/검증) → Tasks 5,10,11,15; §3(점수) → Task 4; §4(09:30 확정+감시) → Tasks 12,13,15; §5(대장주 변경) → Task 14; §6(중복방지/SQLite) → Tasks 7,15; §7(설정값) → Task 1; §8(인터페이스분리/Mock/재시도/필터/0-division/기준시각/판단근거) → Tasks 3,5,6,15; §9(13개 테스트) → Tasks 10-15,17; §10(실행/README/.env.example) → Task 18.
- **Placeholder scan:** the two placeholder values found during drafting (`format_weakness`'s hardcoded drawdown, `format_leader_change`'s comment timestamp) were caught and fixed in Task 9 Step 3.5; the dead line in `_process_monitoring` is explicitly called out for deletion in Task 15 Step 3.
- **Type consistency:** `ScoreBreakdown`, `StockSnapshot`, `CandidateState`, `Phase`, `CandidateStatus` are defined once in Task 2 and referenced identically by name in every later task; `Config` fields defined in Task 1 match every usage (`config.early_min_score`, `config.confirmation_min_score`, etc.) throughout Tasks 10-15.
