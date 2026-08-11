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
