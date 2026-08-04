import json
import os
import notifier

SAMPLE_RESULT = {
    "date": "2026-08-03", "time": "15:10",
    "market": {"kospi": {"index": 2800.5, "change_pct": 0.5},
               "kosdaq": {"index": 850.3, "change_pct": -0.3},
               "us_market": None, "overnight_futures": None},
    "picks": [{
        "rank": 1, "code": "000660", "name": "SK하이닉스", "market": "KOSPI",
        "current_price": 1567000, "daily_return": 5.2, "trade_value_yuk": 8500,
        "pattern": "신고가", "score": 87, "details": ["거래대금 8500억 (15점)"],
        "exit_rules": {"take_profit_1": 1614010, "take_profit_2": 1645350,
                       "stop_loss_tight": 1535660, "stop_loss_max": 1504320,
                       "time_cut": "10:00", "strategy": "시초가 갭상승 시 익절"},
    }],
}


def test_print_to_terminal_includes_key_fields(capsys):
    text = notifier.print_to_terminal(SAMPLE_RESULT)
    assert "SK하이닉스" in text
    assert "87" in text
    assert "신고가" in text
    captured = capsys.readouterr()
    assert "SK하이닉스" in captured.out


def test_save_json_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "OUTPUT_DIR", str(tmp_path))
    path = notifier.save_json(SAMPLE_RESULT)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["picks"][0]["code"] == "000660"


def test_send_telegram_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", None)
    sent = notifier.send_telegram(SAMPLE_RESULT)
    assert sent is False


def test_top_reasons_sorts_by_score_desc():
    details = [
        "거래대금 500억 (5점)",
        "이평 정배열 (15점)",
        "외국인 순매수 (10점)",
        "수급 데이터 없음 (0점)",
    ]
    result = notifier._top_reasons(details, n=3)
    assert result == [
        "이평 정배열 (15점)",
        "외국인 순매수 (10점)",
        "거래대금 500억 (5점)",
    ]


def test_top_reasons_handles_unparseable_score():
    details = ["점수 없는 항목", "이평 정배열 (15점)"]
    result = notifier._top_reasons(details, n=3)
    assert result[0] == "이평 정배열 (15점)"
    assert "점수 없는 항목" in result


def test_top_reasons_empty_list_returns_empty():
    assert notifier._top_reasons([], n=3) == []


def test_send_telegram_includes_reasons_and_exit_rules(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "dummy-chat")

    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    sent = notifier.send_telegram(SAMPLE_RESULT)

    assert sent is True
    text = captured["json"]["text"]
    assert "SK하이닉스" in text
    assert "거래대금 8500억 (15점)" in text
    assert "1,614,010" in text
    assert "1,645,350" in text
    assert "1,535,660" in text
    assert "1,504,320" in text
    assert "시초가 갭상승 시 익절" in text
    assert "10:00" in text


def test_send_telegram_omits_reason_line_when_details_empty(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "dummy-chat")

    result = json.loads(json.dumps(SAMPLE_RESULT))
    result["picks"][0]["details"] = []

    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    notifier.send_telegram(result)
    text = captured["json"]["text"]
    assert "이유:" not in text
