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


def test_run_once_dedupes_repeated_confirmation_alert(engine, capsys):
    for minute in (6, 8, 12, 18, 24, 30, 30):
        engine.run_once(datetime.datetime(2026, 8, 11, 9, minute))
    captured = capsys.readouterr()
    assert captured.out.count("[09:30 오전 주도주 1차 확정]") == 1
