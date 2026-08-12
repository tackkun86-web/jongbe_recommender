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
    eng.store.close()
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
