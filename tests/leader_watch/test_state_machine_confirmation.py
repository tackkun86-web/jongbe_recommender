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
