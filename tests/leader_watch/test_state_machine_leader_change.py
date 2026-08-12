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
