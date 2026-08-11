import datetime
import os
import tempfile

import pytest
from leader_watch.store import AlertStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store_obj = AlertStore(path)
    yield store_obj
    store_obj.close()
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
        s1.close()
        s2.close()
    finally:
        os.remove(path)
