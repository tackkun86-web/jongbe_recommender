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
