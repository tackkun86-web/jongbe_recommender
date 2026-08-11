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
