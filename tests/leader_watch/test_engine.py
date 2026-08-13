# tests/leader_watch/test_engine.py
import datetime
import os
import tempfile
from dataclasses import replace

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
    eng.store.close()
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


def test_confirmation_alert_includes_gap_tier(engine, capsys):
    for minute in (6, 8, 12, 18, 24, 30):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute))
    out = capsys.readouterr().out
    confirmation_body = out.split("[09:30 오전 주도주 1차 확정]")[1]
    assert "갭 등급: " in confirmation_body
    assert "확인 불가" not in confirmation_body.split("갭 등급: ")[1].splitlines()[0]


def test_recovered_candidate_folds_back_into_confirmed_so_monitoring_continues(engine, capsys):
    from leader_watch.models import CandidateState, CandidateStatus, Phase, StockSnapshot

    now = datetime.datetime(2026, 8, 11, 9, 45)
    snap = StockSnapshot(
        code="REC01", name="회복전자", market="KOSPI", timestamp=now,
        current_price=11000, prev_close=10000, open_price=10200, high_price=11000, low_price=10100,
        cum_volume=3_000_000, cum_trading_value=40_000_000_000, market_trading_value_rank=3,
        execution_strength=150.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
        avg_trading_value_same_time_20d=3_000_000_000, avg_volume_same_time_20d=300_000,
    )
    engine.candidates["REC01"] = CandidateState(
        code="REC01", name="회복전자", phase=Phase.MONITORING,
        status=CandidateStatus.WEAKENED, score=60.0, high_since_confirm=11000,
    )

    engine._process_monitoring([snap], now, "2026-08-11")

    assert "[주도력 재회복]" in capsys.readouterr().out
    # RECOVERED must not be a terminal/resting state — it folds back to CONFIRMED so the
    # stock keeps matching the monitoring and leader-change filters.
    assert engine.candidates["REC01"].status is CandidateStatus.CONFIRMED


def test_weakness_alert_reports_a_recomputed_current_score(engine, capsys):
    from leader_watch.models import CandidateState, CandidateStatus, Phase, StockSnapshot

    now = datetime.datetime(2026, 8, 11, 9, 45)
    snap = StockSnapshot(
        code="WK01", name="약화전자", market="KOSPI", timestamp=now,
        current_price=9500, prev_close=10000, open_price=10200, high_price=10800, low_price=9400,
        cum_volume=500_000, cum_trading_value=4_750_000_000, market_trading_value_rank=45,
        execution_strength=80.0, theme="반도체", theme_trading_value_rank=4,
        news_today=False, news_continuing=False,
    )
    engine.candidates["WK01"] = CandidateState(
        code="WK01", name="약화전자", phase=Phase.MONITORING,
        status=CandidateStatus.CONFIRMED, score=90.0, market_rank=3, theme_rank=1, high_since_confirm=10800,
    )

    engine._process_monitoring([snap], now, "2026-08-11")

    out = capsys.readouterr().out
    assert "[주도력 약화]" in out
    assert engine.candidates["WK01"].score != 90.0
    assert "90/100 -> 90/100" not in out


def test_run_once_dedupes_repeated_confirmation_alert(engine, capsys):
    for minute in (6, 8, 12, 18, 24, 30, 30):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute))
    captured = capsys.readouterr()
    assert captured.out.count("[09:30 오전 주도주 1차 확정]") == 1


def test_confirmation_fires_on_wall_clock_ticks_with_seconds(engine, capsys):
    """Regression: real polling never lands on exactly 09:30:00.000000.

    Before the once-per-day latch, `now.time() == confirmation_time` meant the whole
    confirmation phase (and every downstream alert) was dead in production.
    """
    for minute in (6, 8, 12, 18, 24):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute, 0))

    for tick in (
        datetime.datetime(2026, 8, 11, 9, 29, 58, 400_000),
        datetime.datetime(2026, 8, 11, 9, 30, 0, 900_000),
        datetime.datetime(2026, 8, 11, 9, 30, 2, 900_000),
    ):
        engine.run_once(tick)

    out = capsys.readouterr().out
    assert out.count("[09:30 오전 주도주 1차 확정]") == 1
    assert engine._confirmation_done is True


def test_confirmation_latch_resets_on_a_new_session_day(engine):
    engine.run_once(datetime.datetime(2026, 8, 11, 9, 30, 1))
    assert engine._confirmation_done is True
    engine.run_once(datetime.datetime(2026, 8, 12, 9, 6, 1))
    assert engine._confirmation_done is False
    assert engine._session_date == "2026-08-12"


def test_run_once_warns_when_holiday_calendar_year_is_uncovered(engine, capsys):
    engine.run_once(datetime.datetime(2027, 1, 4, 9, 6))  # Monday, uncovered year
    err = capsys.readouterr().err
    assert "휴장일 캘린더" in err
    assert "2027" in err


def test_run_once_rehydrates_candidates_persisted_earlier_today(engine):
    from leader_watch.models import CandidateStatus, Phase

    now = datetime.datetime(2026, 8, 11, 9, 6)
    engine.store.upsert_candidate(
        "OLD01", "2026-08-11", "복구대상", Phase.VALIDATION.value,
        CandidateStatus.REJECTED.value, 42.0, now,
    )

    engine.run_once(now)

    restored = engine.candidates["OLD01"]
    assert restored.name == "복구대상"
    assert restored.phase is Phase.VALIDATION
    assert restored.status is CandidateStatus.REJECTED
    assert restored.score == 42.0


def test_run_loop_survives_a_provider_error_and_keeps_polling(engine, capsys):
    calls = {"n": 0}

    def exploding_run_once(now):
        calls["n"] += 1
        raise ConnectionError("feed down")

    engine.run_once = exploding_run_once
    engine.config = replace(engine.config, poll_interval_seconds=0)

    fake_times = [
        datetime.datetime(2026, 8, 11, 9, 30, 1),
        datetime.datetime(2026, 8, 11, 9, 30, 3),
        datetime.datetime(2026, 8, 11, 10, 30, 1),  # past monitoring_end_time -> loop breaks
    ]
    engine._now = lambda: fake_times.pop(0)

    engine.run()  # must not raise

    assert calls["n"] == 3
    assert "폴링 중 오류 발생" in capsys.readouterr().err


class _NotImplementedProvider:
    """Minimal provider double whose get_snapshot always raises NotImplementedError."""

    def get_snapshot(self, *args, **kwargs):
        raise NotImplementedError("provider not implemented")


def test_run_loop_reraises_not_implemented_provider(engine):
    engine.provider = _NotImplementedProvider()
    engine.config = replace(engine.config, poll_interval_seconds=0)
    engine._now = lambda: datetime.datetime(2026, 8, 11, 9, 30, 1)

    with pytest.raises(NotImplementedError):
        engine.run()
