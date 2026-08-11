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
    snap = _snapshot(current_price=10100)
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
